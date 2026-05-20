import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.provisioning import ProvisioningTask
from backend.models.user import User
from backend.models.entitlement import UserEntitlement
from backend.models.role import UserRole, Role
from backend.models.application import Application, Connector
from backend.config import settings

logger = logging.getLogger(__name__)


class ProvisioningService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_provisioning_task(
        self,
        task_type: str,
        target_user_id: str,
        application_id: Optional[str],
        connector_id: Optional[str],
        payload: dict,
        tenant_id: str,
        scheduled_at: datetime = None,
    ) -> ProvisioningTask:
        # If connector_id not provided, resolve from application
        if not connector_id and application_id:
            conn_result = await self.db.execute(
                select(Connector).where(
                    and_(
                        Connector.application_id == application_id,
                        Connector.tenant_id == tenant_id,
                        Connector.is_active == True,
                        Connector.deleted_at.is_(None),
                    )
                ).limit(1)
            )
            connector = conn_result.scalar_one_or_none()
            if connector:
                connector_id = str(connector.id)

        task = ProvisioningTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            task_type=task_type,
            target_user_id=target_user_id,
            application_id=application_id,
            connector_id=connector_id,
            payload=payload,
            status="pending",
            attempts=0,
            max_attempts=settings.PROVISIONING_MAX_ATTEMPTS if hasattr(settings, "PROVISIONING_MAX_ATTEMPTS") else 3,
            scheduled_at=scheduled_at or datetime.now(timezone.utc),
        )
        self.db.add(task)
        await self.db.flush()

        # Queue Celery task
        try:
            from backend.tasks.provisioning_tasks import execute_provisioning_task
            if scheduled_at and scheduled_at > datetime.now(timezone.utc):
                execute_provisioning_task.apply_async(
                    args=[str(task.id)],
                    eta=scheduled_at,
                )
            else:
                execute_provisioning_task.delay(str(task.id))
        except Exception:
            logger.warning("Failed to queue Celery provisioning task %s", task.id, exc_info=True)

        await self.db.commit()
        return task

    async def execute_provisioning(self, task: ProvisioningTask) -> dict:
        task.status = "in_progress"
        task.attempts = (task.attempts or 0) + 1
        task.started_at = datetime.now(timezone.utc)
        await self.db.flush()

        try:
            # Load connector
            if task.connector_id:
                connector_result = await self.db.execute(
                    select(Connector).where(Connector.id == task.connector_id)
                )
                connector = connector_result.scalar_one_or_none()
            else:
                connector = None

            result = await self._dispatch_to_connector(task, connector)

            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            task.result = result

            # Update entitlements based on task type
            await self._update_entitlements_after_provisioning(task)

            await self.db.commit()
            return result

        except Exception as e:
            logger.error("Provisioning task %s failed: %s", task.id, e, exc_info=True)
            task.status = "failed" if task.attempts >= task.max_attempts else "pending"
            task.error_message = str(e)
            if task.status == "failed":
                task.failed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    async def _dispatch_to_connector(self, task: ProvisioningTask, connector: Optional[Connector]) -> dict:
        if not connector:
            # Fallback: manual provisioning — just log
            logger.info(
                "No connector for task %s (type=%s). Manual provisioning required.",
                task.id,
                task.task_type,
            )
            return {"status": "manual_required", "task_id": str(task.id)}

        connector_type = connector.connector_type

        if connector_type == "scim":
            return await self._execute_scim(task, connector)
        elif connector_type == "ldap":
            return await self._execute_ldap(task, connector)
        elif connector_type == "rest_api":
            return await self._execute_rest_api(task, connector)
        elif connector_type == "csv_export":
            return await self._execute_csv_export(task, connector)
        else:
            raise ValueError(f"Unsupported connector type: {connector_type}")

    async def _execute_scim(self, task: ProvisioningTask, connector: Connector) -> dict:
        import httpx
        config = connector.config or {}
        base_url = config.get("base_url", "").rstrip("/")
        token = config.get("bearer_token", "")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/scim+json"}

        user = await self.db.get(User, task.target_user_id)
        if not user:
            raise ValueError("Target user not found")

        async with httpx.AsyncClient(timeout=30) as client:
            if task.task_type in ("create_account", "grant_role"):
                payload = {
                    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                    "userName": user.email,
                    "name": {
                        "givenName": user.first_name,
                        "familyName": user.last_name,
                    },
                    "emails": [{"value": user.email, "primary": True}],
                    "active": True,
                }
                response = await client.post(f"{base_url}/Users", json=payload, headers=headers)
                response.raise_for_status()
                return {"scim_id": response.json().get("id"), "status": "created"}

            elif task.task_type in ("disable_account", "revoke_role", "deprovision"):
                scim_id = task.payload.get("scim_id")
                if not scim_id:
                    # Search for user
                    resp = await client.get(
                        f"{base_url}/Users",
                        params={"filter": f'userName eq "{user.email}"'},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    resources = resp.json().get("Resources", [])
                    scim_id = resources[0]["id"] if resources else None

                if scim_id:
                    patch_payload = {
                        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                        "Operations": [{"op": "replace", "path": "active", "value": False}],
                    }
                    response = await client.patch(
                        f"{base_url}/Users/{scim_id}", json=patch_payload, headers=headers
                    )
                    response.raise_for_status()
                    return {"scim_id": scim_id, "status": "disabled"}
                return {"status": "user_not_found"}

        return {"status": "noop"}

    async def _execute_ldap(self, task: ProvisioningTask, connector: Connector) -> dict:
        # LDAP operations via ldap3
        try:
            import ldap3
        except ImportError:
            raise RuntimeError("ldap3 is not installed")

        config = connector.config or {}
        server = ldap3.Server(config["host"], port=config.get("port", 389), use_ssl=config.get("use_ssl", False))
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_password"], auto_bind=True)

        user = await self.db.get(User, task.target_user_id)
        if not user:
            raise ValueError("Target user not found")

        base_dn = config.get("base_dn", "")
        user_dn = f"cn={user.display_name},{config.get('users_ou', 'ou=users')},{base_dn}"

        if task.task_type == "create_account":
            attributes = {
                "objectClass": ["top", "person", "organizationalPerson", "inetOrgPerson"],
                "cn": user.display_name,
                "sn": user.last_name,
                "givenName": user.first_name,
                "mail": user.email,
                "uid": user.email.split("@")[0],
            }
            conn.add(user_dn, attributes=attributes)
            if conn.result["result"] not in (0, 68):  # 68 = already exists
                raise RuntimeError(f"LDAP add failed: {conn.result}")
            return {"dn": user_dn, "status": "created"}

        elif task.task_type in ("disable_account", "deprovision"):
            conn.modify(user_dn, {"pwdAccountLockedTime": [(ldap3.MODIFY_REPLACE, ["000001010000Z"])]})
            return {"dn": user_dn, "status": "disabled"}

        conn.unbind()
        return {"status": "noop"}

    async def _execute_rest_api(self, task: ProvisioningTask, connector: Connector) -> dict:
        import httpx
        config = connector.config or {}
        base_url = config.get("base_url", "").rstrip("/")
        auth_type = config.get("auth_type", "bearer")
        headers = {"Content-Type": "application/json"}

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {config.get('token', '')}"
        elif auth_type == "basic":
            import base64
            creds = base64.b64encode(f"{config['username']}:{config['password']}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        elif auth_type == "api_key":
            headers[config.get("api_key_header", "X-API-Key")] = config.get("api_key", "")

        endpoint_map = {
            "create_account": ("POST", config.get("create_endpoint", "/users")),
            "disable_account": ("PATCH", config.get("disable_endpoint", "/users/{user_id}/disable")),
            "deprovision": ("DELETE", config.get("delete_endpoint", "/users/{user_id}")),
            "grant_role": ("POST", config.get("grant_role_endpoint", "/users/{user_id}/roles")),
            "revoke_role": ("DELETE", config.get("revoke_role_endpoint", "/users/{user_id}/roles/{role_id}")),
        }

        method, endpoint = endpoint_map.get(task.task_type, ("POST", "/provision"))

        # Substitute path params
        endpoint = endpoint.format(
            user_id=task.payload.get("external_user_id", str(task.target_user_id)),
            role_id=task.payload.get("role_id", ""),
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, f"{base_url}{endpoint}", json=task.payload, headers=headers)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return {"status": response.status_code, "body": response.text[:500]}

    async def _execute_csv_export(self, task: ProvisioningTask, connector: Connector) -> dict:
        # Export to file (MinIO/S3) for systems that accept CSV imports
        import csv
        import io
        from backend.utils.storage import StorageClient

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(task.payload.keys()))
        writer.writeheader()
        writer.writerow(task.payload)

        storage = StorageClient()
        file_path = f"provisioning/{task.tenant_id}/{task.id}.csv"
        await storage.upload_bytes(file_path, buf.getvalue().encode())

        return {"file_path": file_path, "status": "exported"}

    async def _update_entitlements_after_provisioning(self, task: ProvisioningTask):
        if task.task_type in ("grant_role", "create_account"):
            role_id = task.payload.get("role_id")
            if role_id:
                existing = await self.db.execute(
                    select(UserRole).where(
                        and_(
                            UserRole.user_id == task.target_user_id,
                            UserRole.role_id == role_id,
                            UserRole.tenant_id == task.tenant_id,
                            UserRole.deleted_at.is_(None),
                        )
                    )
                )
                if not existing.scalar_one_or_none():
                    ur = UserRole(
                        user_id=task.target_user_id,
                        role_id=role_id,
                        tenant_id=task.tenant_id,
                        granted_at=datetime.now(timezone.utc),
                        granted_by=task.created_by if hasattr(task, "created_by") else None,
                    )
                    self.db.add(ur)

        elif task.task_type in ("revoke_role", "deprovision", "disable_account"):
            role_id = task.payload.get("role_id")
            if role_id:
                await self.db.execute(
                    update(UserRole)
                    .where(
                        and_(
                            UserRole.user_id == task.target_user_id,
                            UserRole.role_id == role_id,
                            UserRole.tenant_id == task.tenant_id,
                            UserRole.deleted_at.is_(None),
                        )
                    )
                    .values(deleted_at=datetime.now(timezone.utc))
                )
            elif task.task_type in ("deprovision", "disable_account"):
                # Revoke all roles
                await self.db.execute(
                    update(UserRole)
                    .where(
                        and_(
                            UserRole.user_id == task.target_user_id,
                            UserRole.tenant_id == task.tenant_id,
                            UserRole.deleted_at.is_(None),
                        )
                    )
                    .values(deleted_at=datetime.now(timezone.utc))
                )
                # Also revoke user entitlements
                await self.db.execute(
                    update(UserEntitlement)
                    .where(
                        and_(
                            UserEntitlement.user_id == task.target_user_id,
                            UserEntitlement.tenant_id == task.tenant_id,
                            UserEntitlement.deleted_at.is_(None),
                        )
                    )
                    .values(deleted_at=datetime.now(timezone.utc))
                )

    async def deprovision_all_access(
        self,
        user_id: str,
        tenant_id: str,
    ) -> List[ProvisioningTask]:
        # Find all active entitlements
        ents_result = await self.db.execute(
            select(UserEntitlement).where(
                and_(
                    UserEntitlement.user_id == user_id,
                    UserEntitlement.tenant_id == tenant_id,
                    UserEntitlement.deleted_at.is_(None),
                )
            )
        )
        entitlements = ents_result.scalars().all()

        # Find all active roles
        roles_result = await self.db.execute(
            select(UserRole).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_roles = roles_result.scalars().all()

        tasks = []

        # Deprovision entitlements
        for ent in entitlements:
            task = await self.create_provisioning_task(
                task_type="deprovision",
                target_user_id=user_id,
                application_id=str(ent.application_id) if ent.application_id else None,
                connector_id=None,
                payload={"entitlement_id": str(ent.id), "permission_name": ent.permission_name},
                tenant_id=tenant_id,
            )
            tasks.append(task)

        # Deprovision roles
        for ur in user_roles:
            task = await self.create_provisioning_task(
                task_type="revoke_role",
                target_user_id=user_id,
                application_id=None,
                connector_id=None,
                payload={"role_id": str(ur.role_id)},
                tenant_id=tenant_id,
            )
            tasks.append(task)

        return tasks

    async def provision_birthright_access(
        self,
        user: User,
        tenant_id: str,
    ) -> List[ProvisioningTask]:
        from backend.models.role import BirthrightRule

        # Find user's department and role from profile
        profile_result = await self.db.execute(
            select(User).options(
                __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(User.profile)
            ).where(User.id == user.id)
        )
        user_with_profile = profile_result.scalar_one_or_none()
        profile = user_with_profile.profile if user_with_profile else None

        if not profile:
            logger.info("No profile for user %s, skipping birthright provisioning", user.id)
            return []

        # Find matching birthright rules
        conditions = [
            BirthrightRule.tenant_id == tenant_id,
            BirthrightRule.is_active == True,
            BirthrightRule.deleted_at.is_(None),
        ]
        dept_cond = or_(
            BirthrightRule.department_id == profile.department_id,
            BirthrightRule.department_id.is_(None),
        )
        conditions.append(dept_cond)

        if profile.employment_type:
            conditions.append(
                or_(
                    BirthrightRule.employment_type == profile.employment_type,
                    BirthrightRule.employment_type.is_(None),
                )
            )

        rules_result = await self.db.execute(
            select(BirthrightRule).where(and_(*conditions))
        )
        rules = rules_result.scalars().all()

        tasks = []
        for rule in rules:
            task = await self.create_provisioning_task(
                task_type="grant_role",
                target_user_id=str(user.id),
                application_id=str(rule.application_id) if rule.application_id else None,
                connector_id=None,
                payload={"role_id": str(rule.role_id), "birthright_rule_id": str(rule.id)},
                tenant_id=tenant_id,
            )
            tasks.append(task)

        return tasks

    async def verify_provisioning(self, task: ProvisioningTask) -> bool:
        if not task.connector_id:
            # Can't verify without connector
            return task.status == "completed"

        connector_result = await self.db.execute(
            select(Connector).where(Connector.id == task.connector_id)
        )
        connector = connector_result.scalar_one_or_none()
        if not connector:
            return False

        user = await self.db.get(User, task.target_user_id)
        if not user:
            return False

        try:
            if connector.connector_type == "scim":
                import httpx
                config = connector.config or {}
                base_url = config.get("base_url", "").rstrip("/")
                token = config.get("bearer_token", "")
                headers = {"Authorization": f"Bearer {token}"}
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{base_url}/Users",
                        params={"filter": f'userName eq "{user.email}"'},
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        return False
                    resources = resp.json().get("Resources", [])
                    if not resources:
                        return task.task_type in ("disable_account", "deprovision")
                    remote_user = resources[0]
                    is_active = remote_user.get("active", True)
                    if task.task_type in ("disable_account", "deprovision"):
                        return not is_active
                    return is_active

            elif connector.connector_type == "rest_api":
                config = connector.config or {}
                verify_endpoint = config.get("verify_endpoint")
                if not verify_endpoint:
                    return task.status == "completed"
                import httpx
                headers = {"Authorization": f"Bearer {config.get('token', '')}"}
                external_id = (task.result or {}).get("id") or str(task.target_user_id)
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{config['base_url'].rstrip('/')}{verify_endpoint}/{external_id}",
                        headers=headers,
                    )
                    return resp.status_code == 200

        except Exception:
            logger.warning("Verification check failed for task %s", task.id, exc_info=True)
            return False

        return task.status == "completed"

    async def retry_failed_tasks(self, tenant_id: Optional[str] = None):
        conditions = [
            ProvisioningTask.status == "pending",
            ProvisioningTask.attempts < ProvisioningTask.max_attempts,
        ]
        if tenant_id:
            conditions.append(ProvisioningTask.tenant_id == tenant_id)

        result = await self.db.execute(
            select(ProvisioningTask).where(and_(*conditions)).limit(100)
        )
        tasks = result.scalars().all()

        queued = 0
        for task in tasks:
            try:
                from backend.tasks.provisioning_tasks import execute_provisioning_task
                execute_provisioning_task.delay(str(task.id))
                queued += 1
            except Exception:
                logger.warning("Failed to re-queue task %s", task.id, exc_info=True)

        return {"queued": queued, "total_eligible": len(tasks)}
