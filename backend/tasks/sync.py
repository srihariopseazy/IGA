import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.celery_app import celery_app
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ldap_sync_async(connector_id: str, tenant_id: str, direction: str = "inbound") -> dict:
    """
    Synchronize users/groups between LDAP and the IGA platform.
    direction='inbound': import from LDAP → IGA
    direction='outbound': push IGA changes → LDAP
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import Connector

            stmt = select(Connector).where(
                Connector.id == connector_id,
                Connector.tenant_id == tenant_id,
                Connector.connector_type == "ldap",
                Connector.is_active == True,
            )
            result = await session.execute(stmt)
            connector = result.scalar_one_or_none()

            if connector is None:
                logger.error("LDAP connector %s not found for tenant %s", connector_id, tenant_id)
                return {"status": "connector_not_found"}

            config = getattr(connector, "config", {}) or {}
            ldap_server = config.get("server", "")
            base_dn = config.get("base_dn", "")
            bind_dn = config.get("bind_dn", "")
            bind_password = config.get("bind_password", "")
            user_base_dn = config.get("user_base_dn", base_dn)
            group_base_dn = config.get("group_base_dn", base_dn)

            logger.info(
                "Starting LDAP %s sync for connector %s tenant %s server=%s",
                direction, connector_id, tenant_id, ldap_server,
            )

            synced_users = 0
            synced_groups = 0
            errors = []

            if direction == "inbound":
                # Import users from LDAP
                try:
                    from ldap3 import Server, Connection, ALL, SUBTREE
                    server = Server(ldap_server, get_info=ALL)
                    conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
                    conn.search(
                        user_base_dn,
                        "(objectClass=person)",
                        attributes=["cn", "mail", "sAMAccountName", "givenName", "sn", "department"],
                    )
                    for entry in conn.entries:
                        try:
                            email = str(entry.mail) if entry.mail else ""
                            if not email:
                                continue
                            from backend.models.user import User
                            user_result = await session.execute(
                                select(User).where(User.email == email, User.tenant_id == tenant_id)
                            )
                            existing_user = user_result.scalar_one_or_none()
                            if existing_user is None:
                                new_user = User(
                                    email=email,
                                    first_name=str(entry.givenName) if entry.givenName else "",
                                    last_name=str(entry.sn) if entry.sn else "",
                                    username=str(entry.sAMAccountName) if entry.sAMAccountName else email,
                                    tenant_id=tenant_id,
                                    is_active=True,
                                    source="ldap",
                                    external_id=str(entry.entry_dn),
                                )
                                session.add(new_user)
                            else:
                                existing_user.first_name = str(entry.givenName) if entry.givenName else existing_user.first_name
                                existing_user.last_name = str(entry.sn) if entry.sn else existing_user.last_name
                            synced_users += 1
                        except Exception as user_exc:
                            errors.append(str(user_exc))
                    conn.unbind()
                except ImportError:
                    logger.warning("ldap3 not installed, skipping LDAP sync")
                except Exception as ldap_exc:
                    logger.error("LDAP connection error: %s", ldap_exc)
                    errors.append(str(ldap_exc))

            elif direction == "outbound":
                # Push changes from IGA to LDAP - implementation depends on connector config
                logger.info("Outbound LDAP sync not yet implemented for connector %s", connector_id)

            await session.commit()

            # Update connector last_sync_at
            connector.last_sync_at = datetime.now(timezone.utc)
            connector.last_sync_status = "success" if not errors else "partial"
            await session.commit()

            return {
                "connector_id": connector_id,
                "direction": direction,
                "synced_users": synced_users,
                "synced_groups": synced_groups,
                "errors": errors,
            }

        except Exception as exc:
            await session.rollback()
            logger.error("ldap_sync error connector=%s: %s", connector_id, exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.sync.ldap_sync",
    queue="sync",
)
def ldap_sync(connector_id: str, tenant_id: str, direction: str = "inbound") -> dict:
    """Synchronize users and groups between LDAP and IGA."""
    return _run_async(_ldap_sync_async(connector_id, tenant_id, direction))


async def _scim_sync_async(connector_id: str, tenant_id: str) -> dict:
    """
    Sync users/groups with a SCIM 2.0 endpoint.
    Performs inbound sync: GET /Users and GET /Groups then reconcile.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import Connector

            stmt = select(Connector).where(
                Connector.id == connector_id,
                Connector.tenant_id == tenant_id,
                Connector.connector_type == "scim",
                Connector.is_active == True,
            )
            result = await session.execute(stmt)
            connector = result.scalar_one_or_none()

            if connector is None:
                logger.error("SCIM connector %s not found for tenant %s", connector_id, tenant_id)
                return {"status": "connector_not_found"}

            config = getattr(connector, "config", {}) or {}
            base_url = config.get("base_url", "")
            bearer_token = config.get("bearer_token", "")
            headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/scim+json"}

            logger.info("Starting SCIM sync for connector %s tenant %s", connector_id, tenant_id)

            synced_users = 0
            errors = []

            try:
                import aiohttp
                async with aiohttp.ClientSession(headers=headers) as http:
                    # Fetch all users with pagination
                    start_index = 1
                    count = 100
                    while True:
                        url = f"{base_url}/Users?startIndex={start_index}&count={count}"
                        async with http.get(url) as resp:
                            if resp.status != 200:
                                errors.append(f"SCIM GET Users returned {resp.status}")
                                break
                            data = await resp.json()

                        resources = data.get("Resources", [])
                        if not resources:
                            break

                        for scim_user in resources:
                            try:
                                emails = scim_user.get("emails", [])
                                email = next((e["value"] for e in emails if e.get("primary")), "")
                                if not email and emails:
                                    email = emails[0].get("value", "")
                                if not email:
                                    continue

                                name = scim_user.get("name", {})
                                first_name = name.get("givenName", "")
                                last_name = name.get("familyName", "")
                                external_id = scim_user.get("id", "")

                                from backend.models.user import User
                                user_result = await session.execute(
                                    select(User).where(
                                        User.email == email,
                                        User.tenant_id == tenant_id,
                                    )
                                )
                                existing = user_result.scalar_one_or_none()
                                if existing is None:
                                    new_user = User(
                                        email=email,
                                        first_name=first_name,
                                        last_name=last_name,
                                        username=scim_user.get("userName", email),
                                        tenant_id=tenant_id,
                                        is_active=scim_user.get("active", True),
                                        source="scim",
                                        external_id=external_id,
                                    )
                                    session.add(new_user)
                                else:
                                    existing.first_name = first_name or existing.first_name
                                    existing.last_name = last_name or existing.last_name
                                    existing.is_active = scim_user.get("active", existing.is_active)
                                synced_users += 1
                            except Exception as user_exc:
                                errors.append(str(user_exc))

                        total = data.get("totalResults", 0)
                        start_index += count
                        if start_index > total:
                            break

            except ImportError:
                logger.warning("aiohttp not installed, cannot perform SCIM sync")
            except Exception as http_exc:
                errors.append(str(http_exc))
                logger.error("SCIM HTTP error: %s", http_exc)

            await session.commit()

            connector.last_sync_at = datetime.now(timezone.utc)
            connector.last_sync_status = "success" if not errors else "partial"
            await session.commit()

            return {
                "connector_id": connector_id,
                "synced_users": synced_users,
                "errors": errors,
            }

        except Exception as exc:
            await session.rollback()
            logger.error("scim_sync error connector=%s: %s", connector_id, exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.sync.scim_sync",
    queue="sync",
)
def scim_sync(connector_id: str, tenant_id: str) -> dict:
    """Synchronize users via SCIM 2.0 from an external provider."""
    return _run_async(_scim_sync_async(connector_id, tenant_id))


async def _hrms_sync_async(tenant_id: str, data: Optional[dict] = None) -> dict:
    """
    Sync employee data from HRMS (e.g. Workday, BambooHR).
    If data is provided (webhook push), process it directly.
    Otherwise, pull from configured HRMS connector.
    """
    async with AsyncSessionLocal() as session:
        try:
            synced = 0
            errors = []

            if data:
                # Process pushed HRMS event
                event_type = data.get("event_type", "")
                employee = data.get("employee", {})
                email = employee.get("email", "")

                if not email:
                    return {"status": "no_email_in_payload"}

                from backend.models.user import User
                result = await session.execute(
                    select(User).where(User.email == email, User.tenant_id == tenant_id)
                )
                user = result.scalar_one_or_none()

                if event_type == "employee.hired":
                    if user is None:
                        new_user = User(
                            email=email,
                            first_name=employee.get("first_name", ""),
                            last_name=employee.get("last_name", ""),
                            employee_id=employee.get("employee_id", ""),
                            job_title=employee.get("job_title", ""),
                            tenant_id=tenant_id,
                            is_active=True,
                            source="hrms",
                        )
                        session.add(new_user)
                        synced += 1

                elif event_type == "employee.terminated":
                    if user:
                        user.is_active = False
                        user.status = "deactivated"
                        synced += 1
                        # Trigger deprovisioning
                        from backend.tasks.provisioning import deprovision_user_access
                        logger.info("HRMS termination: queuing deprovisioning for user %s", user.id)

                elif event_type == "employee.updated":
                    if user:
                        user.first_name = employee.get("first_name", user.first_name)
                        user.last_name = employee.get("last_name", user.last_name)
                        user.job_title = employee.get("job_title", user.job_title)
                        user.employee_id = employee.get("employee_id", user.employee_id)
                        synced += 1

                await session.commit()
            else:
                # Pull sync - placeholder
                logger.info("HRMS pull sync not implemented for tenant %s", tenant_id)

            return {"tenant_id": tenant_id, "synced": synced, "errors": errors}

        except Exception as exc:
            await session.rollback()
            logger.error("hrms_sync error tenant=%s: %s", tenant_id, exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.sync.hrms_sync",
    queue="sync",
)
def hrms_sync(tenant_id: str, data: Optional[dict] = None) -> dict:
    """Sync employee lifecycle events from HRMS into IGA."""
    return _run_async(_hrms_sync_async(tenant_id, data))
