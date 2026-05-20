import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy import func, select, update, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.user import User, UserProfile
from backend.models.role import Role, UserRole
from backend.models.entitlement import UserEntitlement
from backend.models.audit import AuditLog
from backend.models.risk import RiskScore
from backend.utils.security import hash_password, generate_secure_token
from backend.utils.email import EmailService
from backend.utils.redis_client import redis_client
from backend.config import settings

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService()

    async def create_user(
        self,
        data: dict,
        created_by: str,
        tenant_id: str,
    ) -> User:
        # Validate unique email within tenant
        existing = await self.db.execute(
            select(User).where(
                and_(
                    User.email == data["email"].lower(),
                    User.tenant_id == tenant_id,
                    User.deleted_at.is_(None),
                )
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"User with email {data['email']} already exists in this tenant")

        # Hash password (or generate temp password)
        raw_password = data.get("password") or generate_secure_token(12)
        is_temp_password = "password" not in data
        hashed = hash_password(raw_password)

        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email=data["email"].lower(),
            hashed_password=hashed,
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            display_name=data.get("display_name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
            status=data.get("status", "active"),
            employee_id=data.get("employee_id"),
            phone=data.get("phone"),
            avatar_url=data.get("avatar_url"),
            mfa_enabled=False,
            password_changed_at=None if is_temp_password else datetime.now(timezone.utc),
            must_change_password=is_temp_password,
        )
        self.db.add(user)
        await self.db.flush()

        # Create user profile
        profile = UserProfile(
            user_id=user.id,
            tenant_id=tenant_id,
            department_id=data.get("department_id"),
            job_title=data.get("job_title"),
            manager_id=data.get("manager_id"),
            location=data.get("location"),
            cost_center=data.get("cost_center"),
            employment_type=data.get("employment_type", "full_time"),
            start_date=data.get("start_date"),
            contract_end_date=data.get("contract_end_date"),
            hrms_id=data.get("hrms_id"),
        )
        self.db.add(profile)
        await self.db.flush()

        # Create audit log
        await self._audit(
            tenant_id=tenant_id,
            user_id=created_by,
            action="user.create",
            resource_type="user",
            resource_id=str(user.id),
            details={"email": user.email, "created_by": created_by},
        )

        await self.db.commit()

        # Trigger joiner workflow if profile has start_date
        if data.get("trigger_lifecycle", True):
            try:
                from backend.services.lifecycle_service import LifecycleService
                lc = LifecycleService(self.db)
                await lc.handle_joiner(str(user.id), tenant_id, created_by)
            except Exception:
                logger.warning("Joiner lifecycle trigger failed for user %s", user.id, exc_info=True)

        # Send welcome email
        try:
            await self.email_service.send_welcome(
                user.email,
                user.display_name,
                raw_password if is_temp_password else None,
            )
        except Exception:
            logger.warning("Failed to send welcome email to %s", user.email, exc_info=True)

        return user

    async def update_user(
        self,
        user_id: str,
        data: dict,
        updated_by: str,
        tenant_id: str,
    ) -> User:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        # Snapshot before update
        before = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "status": user.status,
        }

        # Apply updates to User
        user_fields = {"email", "first_name", "last_name", "display_name", "phone", "avatar_url", "status"}
        for field in user_fields:
            if field in data:
                val = data[field]
                if field == "email":
                    val = val.lower()
                    # Ensure unique
                    existing = await self.db.execute(
                        select(User).where(
                            and_(
                                User.email == val,
                                User.tenant_id == tenant_id,
                                User.id != user.id,
                                User.deleted_at.is_(None),
                            )
                        )
                    )
                    if existing.scalar_one_or_none():
                        raise ValueError(f"Email {val} already in use")
                setattr(user, field, val)

        # Apply updates to UserProfile
        profile_fields = {
            "department_id", "job_title", "manager_id", "location",
            "cost_center", "employment_type", "start_date", "contract_end_date", "hrms_id",
        }
        profile_data = {k: v for k, v in data.items() if k in profile_fields}
        if profile_data:
            result = await self.db.execute(
                select(UserProfile).where(UserProfile.user_id == user.id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                for field, val in profile_data.items():
                    setattr(profile, field, val)

        await self._audit(
            tenant_id=tenant_id,
            user_id=updated_by,
            action="user.update",
            resource_type="user",
            resource_id=str(user.id),
            details={"before": before, "changes": {k: v for k, v in data.items() if k in user_fields | profile_fields}},
        )
        await self.db.commit()
        return user

    async def lock_user(
        self,
        user_id: str,
        reason: str,
        locked_by: str,
        tenant_id: str,
    ) -> User:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        user.status = "locked"
        user.locked_until = None  # Manual lock — indefinite
        await self._audit(
            tenant_id=tenant_id,
            user_id=locked_by,
            action="user.lock",
            resource_type="user",
            resource_id=str(user.id),
            details={"reason": reason},
        )
        # Revoke all active sessions
        await self._revoke_all_sessions(user_id, tenant_id)
        await self.db.commit()
        return user

    async def unlock_user(
        self,
        user_id: str,
        unlocked_by: str,
        tenant_id: str,
    ) -> User:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        user.status = "active"
        user.locked_until = None
        user.failed_login_attempts = 0
        await redis_client.clear_failed_logins(str(user.id))

        await self._audit(
            tenant_id=tenant_id,
            user_id=unlocked_by,
            action="user.unlock",
            resource_type="user",
            resource_id=str(user.id),
            details={"unlocked_by": unlocked_by},
        )
        await self.db.commit()
        return user

    async def suspend_user(
        self,
        user_id: str,
        reason: str,
        suspended_by: str,
        tenant_id: str,
    ) -> User:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        user.status = "suspended"
        await self._audit(
            tenant_id=tenant_id,
            user_id=suspended_by,
            action="user.suspend",
            resource_type="user",
            resource_id=str(user.id),
            details={"reason": reason},
        )
        await self._revoke_all_sessions(user_id, tenant_id)
        await self.db.commit()
        return user

    async def activate_user(
        self,
        user_id: str,
        activated_by: str,
        tenant_id: str,
    ) -> User:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        user.status = "active"
        user.locked_until = None
        user.failed_login_attempts = 0

        await self._audit(
            tenant_id=tenant_id,
            user_id=activated_by,
            action="user.activate",
            resource_type="user",
            resource_id=str(user.id),
            details={"activated_by": activated_by},
        )
        await self.db.commit()
        return user

    async def delete_user(
        self,
        user_id: str,
        deleted_by: str,
        tenant_id: str,
    ) -> bool:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        now = datetime.now(timezone.utc)
        user.deleted_at = now
        user.status = "deleted"

        # Soft-delete profile
        await self.db.execute(
            update(UserProfile).where(UserProfile.user_id == user.id).values(deleted_at=now)
        )

        await self._audit(
            tenant_id=tenant_id,
            user_id=deleted_by,
            action="user.delete",
            resource_type="user",
            resource_id=str(user.id),
            details={"deleted_by": deleted_by},
        )
        await self._revoke_all_sessions(user_id, tenant_id)
        await self.db.commit()
        return True

    async def offboard_user(
        self,
        user_id: str,
        exit_date: datetime,
        offboarded_by: str,
        tenant_id: str,
    ) -> dict:
        user = await self._get_user(user_id, tenant_id)
        if not user:
            raise ValueError("User not found")

        # Set exit date on profile
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user.id)
            .values(exit_date=exit_date)
        )

        # Revoke all active sessions immediately
        await self._revoke_all_sessions(user_id, tenant_id)

        # Trigger leaver workflow
        from backend.services.lifecycle_service import LifecycleService
        lc = LifecycleService(self.db)
        leaver_result = await lc.handle_leaver(
            user_id=user_id,
            exit_date=exit_date,
            grace_period_days=0,
            tenant_id=tenant_id,
            triggered_by=offboarded_by,
        )

        await self._audit(
            tenant_id=tenant_id,
            user_id=offboarded_by,
            action="user.offboard",
            resource_type="user",
            resource_id=str(user.id),
            details={"exit_date": exit_date.isoformat(), "offboarded_by": offboarded_by},
        )
        await self.db.commit()

        return {
            "user_id": user_id,
            "exit_date": exit_date.isoformat(),
            "lifecycle_result": leaver_result,
        }

    async def get_user_with_details(
        self,
        user_id: str,
        tenant_id: str,
    ) -> dict:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.profile))
            .where(and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None)))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        # Roles
        roles_result = await self.db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                and_(
                    UserRole.user_id == user.id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        roles = roles_result.scalars().all()

        # Entitlements
        ents_result = await self.db.execute(
            select(UserEntitlement).where(
                and_(
                    UserEntitlement.user_id == user.id,
                    UserEntitlement.tenant_id == tenant_id,
                    UserEntitlement.deleted_at.is_(None),
                )
            )
        )
        entitlements = ents_result.scalars().all()

        # Risk score
        risk_result = await self.db.execute(
            select(RiskScore).where(
                and_(RiskScore.user_id == user.id, RiskScore.tenant_id == tenant_id)
            )
        )
        risk = risk_result.scalar_one_or_none()

        return {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "status": user.status,
            "phone": user.phone,
            "avatar_url": user.avatar_url,
            "mfa_enabled": user.mfa_enabled,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "profile": {
                "department_id": str(user.profile.department_id) if user.profile and user.profile.department_id else None,
                "job_title": user.profile.job_title if user.profile else None,
                "manager_id": str(user.profile.manager_id) if user.profile and user.profile.manager_id else None,
                "location": user.profile.location if user.profile else None,
                "employment_type": user.profile.employment_type if user.profile else None,
                "start_date": user.profile.start_date.isoformat() if user.profile and user.profile.start_date else None,
                "contract_end_date": user.profile.contract_end_date.isoformat() if user.profile and user.profile.contract_end_date else None,
            } if user.profile else None,
            "roles": [
                {"id": str(r.id), "name": r.name, "display_name": r.display_name}
                for r in roles
            ],
            "entitlements": [
                {
                    "id": str(e.id),
                    "application_id": str(e.application_id),
                    "permission_name": e.permission_name,
                    "granted_at": e.granted_at.isoformat() if e.granted_at else None,
                }
                for e in entitlements
            ],
            "risk_score": {
                "score": risk.score,
                "level": risk.level,
                "calculated_at": risk.calculated_at.isoformat() if risk.calculated_at else None,
            } if risk else None,
        }

    async def list_users(
        self,
        tenant_id: str,
        page: int = 1,
        per_page: int = 20,
        search: str = None,
        status: str = None,
        department_id: str = None,
    ) -> dict:
        query = select(User).where(
            and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )

        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    User.email.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.display_name.ilike(pattern),
                )
            )

        if status:
            query = query.where(User.status == status)

        if department_id:
            query = query.join(UserProfile, UserProfile.user_id == User.id).where(
                UserProfile.department_id == department_id
            )

        # Total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Paginate
        offset = (page - 1) * per_page
        query = query.order_by(User.created_at.desc()).offset(offset).limit(per_page)
        result = await self.db.execute(query)
        users = result.scalars().all()

        return {
            "users": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "display_name": u.display_name,
                    "status": u.status,
                    "mfa_enabled": u.mfa_enabled,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in users
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }

    async def bulk_import(
        self,
        csv_data: bytes,
        tenant_id: str,
        imported_by: str,
    ) -> dict:
        reader = csv.DictReader(io.StringIO(csv_data.decode("utf-8-sig")))
        required_columns = {"email", "first_name", "last_name"}

        rows = list(reader)
        if not rows:
            return {"success": 0, "errors": [], "total": 0}

        missing_cols = required_columns - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(f"CSV missing required columns: {missing_cols}")

        success_count = 0
        error_rows = []

        for idx, row in enumerate(rows, start=2):  # row 1 = header
            row_num = idx
            email = row.get("email", "").strip()
            if not email:
                error_rows.append({"row": row_num, "error": "Missing email"})
                continue

            # Basic email validation
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                error_rows.append({"row": row_num, "email": email, "error": "Invalid email format"})
                continue

            try:
                await self.create_user(
                    data={
                        "email": email,
                        "first_name": row.get("first_name", "").strip(),
                        "last_name": row.get("last_name", "").strip(),
                        "job_title": row.get("job_title", "").strip() or None,
                        "department_id": row.get("department_id", "").strip() or None,
                        "manager_id": row.get("manager_id", "").strip() or None,
                        "employment_type": row.get("employment_type", "full_time").strip() or "full_time",
                        "employee_id": row.get("employee_id", "").strip() or None,
                        "trigger_lifecycle": False,
                    },
                    created_by=imported_by,
                    tenant_id=tenant_id,
                )
                success_count += 1
            except ValueError as e:
                error_rows.append({"row": row_num, "email": email, "error": str(e)})
            except Exception as e:
                logger.error("Bulk import error at row %d: %s", row_num, e, exc_info=True)
                error_rows.append({"row": row_num, "email": email, "error": "Internal error"})

        return {
            "total": len(rows),
            "success": success_count,
            "failed": len(error_rows),
            "errors": error_rows,
        }

    async def detect_duplicates(self, tenant_id: str) -> List[dict]:
        result = await self.db.execute(
            select(User).where(
                and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
            )
        )
        users = result.scalars().all()

        duplicates = []
        seen: dict = {}

        for user in users:
            # Normalize name for fuzzy matching
            name_key = f"{user.first_name.lower().strip()}_{user.last_name.lower().strip()}"
            domain = user.email.split("@")[1] if "@" in user.email else ""

            composite = f"{name_key}_{domain}"
            if composite in seen:
                existing = seen[composite]
                duplicates.append(
                    {
                        "user_1": {
                            "id": str(existing.id),
                            "email": existing.email,
                            "display_name": existing.display_name,
                        },
                        "user_2": {
                            "id": str(user.id),
                            "email": user.email,
                            "display_name": user.display_name,
                        },
                        "match_type": "name_domain",
                        "confidence": 0.85,
                    }
                )
            else:
                seen[composite] = user

            # Also check exact email prefix duplicates (before @)
            email_prefix = user.email.split("@")[0].lower()
            prefix_key = f"prefix_{email_prefix}_{domain}"
            if prefix_key in seen and seen[prefix_key].id != user.id:
                existing = seen[prefix_key]
                duplicates.append(
                    {
                        "user_1": {"id": str(existing.id), "email": existing.email, "display_name": existing.display_name},
                        "user_2": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
                        "match_type": "email_prefix",
                        "confidence": 0.95,
                    }
                )
            else:
                seen[prefix_key] = user

        return duplicates

    async def reconcile_identities(self, tenant_id: str) -> dict:
        # Find orphaned entitlements (user soft-deleted but entitlements still active)
        result = await self.db.execute(
            select(UserEntitlement)
            .join(User, User.id == UserEntitlement.user_id)
            .where(
                and_(
                    UserEntitlement.tenant_id == tenant_id,
                    UserEntitlement.deleted_at.is_(None),
                    User.deleted_at.isnot(None),
                )
            )
        )
        orphaned_entitlements = result.scalars().all()

        # Find users with no roles (potentially orphaned accounts)
        users_with_roles_subq = select(UserRole.user_id).where(
            and_(UserRole.tenant_id == tenant_id, UserRole.deleted_at.is_(None))
        )
        result2 = await self.db.execute(
            select(User).where(
                and_(
                    User.tenant_id == tenant_id,
                    User.deleted_at.is_(None),
                    User.status == "active",
                    User.id.not_in(users_with_roles_subq),
                )
            )
        )
        users_without_roles = result2.scalars().all()

        # Find accounts where HRMS ID is missing (could be orphaned)
        result3 = await self.db.execute(
            select(User)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                and_(
                    User.tenant_id == tenant_id,
                    User.deleted_at.is_(None),
                    UserProfile.hrms_id.is_(None),
                    UserProfile.employment_type != "service_account",
                )
            )
        )
        no_hrms_id = result3.scalars().all()

        return {
            "orphaned_entitlements": [
                {"entitlement_id": str(e.id), "user_id": str(e.user_id)}
                for e in orphaned_entitlements
            ],
            "users_without_roles": [
                {"user_id": str(u.id), "email": u.email}
                for u in users_without_roles
            ],
            "missing_hrms_id": [
                {"user_id": str(u.id), "email": u.email}
                for u in no_hrms_id
            ],
            "summary": {
                "orphaned_entitlements_count": len(orphaned_entitlements),
                "users_without_roles_count": len(users_without_roles),
                "missing_hrms_id_count": len(no_hrms_id),
            },
        }

    async def _get_user(self, user_id: str, tenant_id: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(
                and_(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def _revoke_all_sessions(self, user_id: str, tenant_id: str):
        from backend.models.user import Session
        result = await self.db.execute(
            select(Session).where(
                and_(
                    Session.user_id == user_id,
                    Session.tenant_id == tenant_id,
                    Session.is_active == True,
                )
            )
        )
        sessions = result.scalars().all()
        for session in sessions:
            session.is_active = False
            await redis_client.blacklist_token(
                str(session.id),
                settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            )

    async def _audit(
        self,
        tenant_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict,
    ):
        log = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            result="success",
            risk_level="low",
        )
        self.db.add(log)
