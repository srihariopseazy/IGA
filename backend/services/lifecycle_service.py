import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user import User, UserProfile

logger = logging.getLogger(__name__)


class LifecycleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle_joiner(
        self,
        user_id: str,
        tenant_id: str,
        triggered_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a new joiner:
        - Provision birthright access (default roles for their department)
        - Send welcome email notification
        - Start joiner workflow
        - Log lifecycle event
        """
        user_result = await self.db.execute(
            select(User).where(
                and_(User.id == user_id, User.tenant_id == tenant_id)
            )
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        actions_taken = []

        # 1. Provision birthright access
        roles_granted = await self._provision_birthright_access(user, tenant_id)
        actions_taken.append(f"Granted {len(roles_granted)} birthright roles")

        # 2. Activate user if pending
        if user.status == "pending":
            user.status = "active"
            actions_taken.append("User status set to active")

        # 3. Send welcome notification
        try:
            await self._send_welcome_notification(user, tenant_id)
            actions_taken.append("Welcome notification sent")
        except Exception as e:
            logger.warning("Failed to send welcome notification: %s", e)

        # 4. Queue joiner workflow
        try:
            from backend.tasks.workflow_tasks import trigger_lifecycle_workflow
            trigger_lifecycle_workflow.delay(
                "joiner", user_id, tenant_id, triggered_by
            )
            actions_taken.append("Joiner workflow queued")
        except Exception as e:
            logger.warning("Failed to queue joiner workflow: %s", e)

        await self.db.commit()

        await self._audit_lifecycle(
            user_id, tenant_id, "lifecycle.joiner", triggered_by,
            {"roles_granted": len(roles_granted), "actions": actions_taken}
        )

        return {
            "event": "joiner",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "actions_taken": actions_taken,
            "roles_granted": roles_granted,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }

    async def handle_mover(
        self,
        user_id: str,
        old_dept_id: Optional[str],
        new_dept_id: Optional[str],
        old_role_id: Optional[str],
        new_role_id: Optional[str],
        tenant_id: str,
        triggered_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a mover (internal transfer):
        - Remove old department roles
        - Grant new department birthright access
        - Update user profile
        - Trigger re-certification if needed
        """
        user_result = await self.db.execute(
            select(User).where(
                and_(User.id == user_id, User.tenant_id == tenant_id)
            )
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        actions_taken = []

        # Update department
        if new_dept_id:
            user.department_id = new_dept_id
            actions_taken.append(f"Department updated to {new_dept_id}")

        # Remove old role if specified
        if old_role_id:
            removed = await self._remove_role(user_id, old_role_id, tenant_id)
            if removed:
                actions_taken.append(f"Removed old role {old_role_id}")

        # Grant new role if specified
        if new_role_id:
            granted = await self._grant_role(user_id, new_role_id, tenant_id, triggered_by)
            if granted:
                actions_taken.append(f"Granted new role {new_role_id}")

        # Provision new birthright access for new department
        if new_dept_id and new_dept_id != old_dept_id:
            new_roles = await self._provision_birthright_access(user, tenant_id)
            actions_taken.append(f"Provisioned {len(new_roles)} birthright roles for new department")

        # Queue mover workflow
        try:
            from backend.tasks.workflow_tasks import trigger_lifecycle_workflow
            trigger_lifecycle_workflow.delay(
                "mover", user_id, tenant_id, triggered_by,
                {
                    "old_dept_id": str(old_dept_id) if old_dept_id else None,
                    "new_dept_id": str(new_dept_id) if new_dept_id else None,
                }
            )
            actions_taken.append("Mover workflow queued")
        except Exception as e:
            logger.warning("Failed to queue mover workflow: %s", e)

        await self.db.commit()

        await self._audit_lifecycle(
            user_id, tenant_id, "lifecycle.mover", triggered_by,
            {
                "old_dept_id": str(old_dept_id) if old_dept_id else None,
                "new_dept_id": str(new_dept_id) if new_dept_id else None,
                "actions": actions_taken,
            }
        )

        return {
            "event": "mover",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "actions_taken": actions_taken,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }

    async def handle_leaver(
        self,
        user_id: str,
        exit_date: Optional[datetime],
        grace_period_days: int,
        tenant_id: str,
        triggered_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a leaver:
        - Deprovision all access (roles, sessions, PAM)
        - Set exit date and status
        - Notify IT/HR
        - Revoke all active sessions
        """
        user_result = await self.db.execute(
            select(User).where(
                and_(User.id == user_id, User.tenant_id == tenant_id)
            )
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        actions_taken = []
        deactivation_date = exit_date or datetime.now(timezone.utc)

        if grace_period_days <= 0:
            # Immediate deactivation
            user.status = "inactive"
            actions_taken.append("User account deactivated")
        else:
            # Schedule deactivation
            actions_taken.append(
                f"Deactivation scheduled for {(deactivation_date + timedelta(days=grace_period_days)).isoformat()}"
            )

        # Update exit date in profile
        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            profile.exit_date = deactivation_date
            actions_taken.append("Exit date recorded")

        # Revoke all sessions
        sessions_revoked = await self._revoke_all_sessions(user_id)
        actions_taken.append(f"Revoked {sessions_revoked} active sessions")

        # Deprovision all roles
        if grace_period_days <= 0:
            roles_removed = await self._deprovision_all_roles(user_id, tenant_id)
            actions_taken.append(f"Removed {roles_removed} role assignments")

        # Terminate PAM sessions
        pam_terminated = await self._terminate_pam_sessions(user_id, tenant_id)
        if pam_terminated > 0:
            actions_taken.append(f"Terminated {pam_terminated} PAM sessions")

        # Queue leaver workflow
        try:
            from backend.tasks.workflow_tasks import trigger_lifecycle_workflow
            trigger_lifecycle_workflow.delay(
                "leaver", user_id, tenant_id, triggered_by,
                {
                    "exit_date": deactivation_date.isoformat(),
                    "grace_period_days": grace_period_days,
                }
            )
            actions_taken.append("Leaver workflow queued")
        except Exception as e:
            logger.warning("Failed to queue leaver workflow: %s", e)

        # Notify IT/HR
        try:
            await self._notify_it_hr_leaver(user, tenant_id, deactivation_date)
            actions_taken.append("IT/HR notified")
        except Exception as e:
            logger.warning("Failed to send IT/HR leaver notification: %s", e)

        await self.db.commit()

        await self._audit_lifecycle(
            user_id, tenant_id, "lifecycle.leaver", triggered_by,
            {
                "exit_date": deactivation_date.isoformat(),
                "grace_period_days": grace_period_days,
                "actions": actions_taken,
            }
        )

        return {
            "event": "leaver",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "actions_taken": actions_taken,
            "exit_date": deactivation_date.isoformat(),
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }

    async def handle_rehire(
        self,
        user_id: str,
        tenant_id: str,
        triggered_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a rehire:
        - Reactivate user account
        - Provision birthright access
        - Clear exit date
        - Send welcome back notification
        """
        user_result = await self.db.execute(
            select(User).where(
                and_(User.id == user_id, User.tenant_id == tenant_id)
            )
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User {user_id} not found")

        actions_taken = []

        # Reactivate
        user.status = "active"
        actions_taken.append("User account reactivated")

        # Clear exit date
        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            profile.exit_date = None
            actions_taken.append("Exit date cleared")

        # Provision birthright access
        roles_granted = await self._provision_birthright_access(user, tenant_id)
        actions_taken.append(f"Granted {len(roles_granted)} birthright roles")

        # Welcome back notification
        try:
            await self._send_welcome_notification(user, tenant_id, is_rehire=True)
            actions_taken.append("Welcome back notification sent")
        except Exception as e:
            logger.warning("Failed to send rehire notification: %s", e)

        await self.db.commit()

        await self._audit_lifecycle(
            user_id, tenant_id, "lifecycle.rehire", triggered_by,
            {"actions": actions_taken}
        )

        return {
            "event": "rehire",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "actions_taken": actions_taken,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }

    async def process_hrms_event(
        self, event: Dict[str, Any], tenant_id: str
    ) -> Dict[str, Any]:
        """
        Dispatch an HRMS event to the appropriate lifecycle handler.

        Expected event structure:
        {
            "event_type": "hire" | "transfer" | "terminate" | "rehire",
            "user_id": "...",
            "effective_date": "...",
            "data": {...}
        }
        """
        event_type = event.get("event_type", "").lower()
        user_id = event.get("user_id")
        if not user_id:
            raise ValueError("event.user_id is required")

        data = event.get("data", {})
        triggered_by = event.get("triggered_by", "hrms")

        if event_type in ("hire", "onboard", "joiner"):
            return await self.handle_joiner(user_id, tenant_id, triggered_by)

        elif event_type in ("transfer", "move", "mover"):
            return await self.handle_mover(
                user_id=user_id,
                old_dept_id=data.get("old_department_id"),
                new_dept_id=data.get("new_department_id"),
                old_role_id=data.get("old_role_id"),
                new_role_id=data.get("new_role_id"),
                tenant_id=tenant_id,
                triggered_by=triggered_by,
            )

        elif event_type in ("terminate", "offboard", "leaver"):
            exit_date_str = event.get("effective_date") or data.get("exit_date")
            exit_date = None
            if exit_date_str:
                try:
                    exit_date = datetime.fromisoformat(exit_date_str)
                except Exception:
                    pass
            grace_period = data.get("grace_period_days", 0)
            return await self.handle_leaver(
                user_id=user_id,
                exit_date=exit_date,
                grace_period_days=grace_period,
                tenant_id=tenant_id,
                triggered_by=triggered_by,
            )

        elif event_type in ("rehire", "reactivate"):
            return await self.handle_rehire(user_id, tenant_id, triggered_by)

        else:
            logger.warning("Unknown HRMS event type: %s", event_type)
            return {
                "event": event_type,
                "user_id": user_id,
                "status": "skipped",
                "reason": f"Unknown event type: {event_type}",
            }

    async def auto_deactivate_contractors(
        self, tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Find contractors whose contract has expired and trigger the leaver process.
        """
        now = datetime.now(timezone.utc)

        profiles_query = (
            select(UserProfile)
            .join(User, User.id == UserProfile.user_id)
            .where(
                and_(
                    UserProfile.employment_type == "contractor",
                    UserProfile.exit_date.isnot(None),
                    UserProfile.exit_date <= now,
                    User.status == "active",
                    User.deleted_at.is_(None),
                )
            )
        )
        if tenant_id:
            profiles_query = profiles_query.where(UserProfile.tenant_id == tenant_id)

        profiles_result = await self.db.execute(profiles_query)
        profiles = profiles_result.scalars().all()

        deactivated = []
        errors = []

        for profile in profiles:
            try:
                result = await self.handle_leaver(
                    user_id=str(profile.user_id),
                    exit_date=profile.exit_date,
                    grace_period_days=0,
                    tenant_id=str(profile.tenant_id),
                    triggered_by="auto_deactivation",
                )
                deactivated.append(str(profile.user_id))
                logger.info(
                    "Auto-deactivated contractor %s (exit_date=%s)",
                    profile.user_id,
                    profile.exit_date,
                )
            except Exception as e:
                errors.append({"user_id": str(profile.user_id), "error": str(e)})
                logger.error("Auto-deactivation failed for %s: %s", profile.user_id, e)

        return {
            "deactivated_count": len(deactivated),
            "deactivated_users": deactivated,
            "errors": errors,
            "run_at": now.isoformat(),
        }

    # ---- Private helpers ----

    async def _provision_birthright_access(
        self, user: User, tenant_id: str
    ) -> List[str]:
        """Grant standard roles based on department or employment type."""
        from backend.models.rbac import Role, UserRole

        # Find the standard "User" role for this tenant
        roles_query = select(Role).where(
            and_(
                Role.tenant_id == tenant_id,
                Role.name.in_(["User", "Standard User"]),
                Role.deleted_at.is_(None),
            )
        )
        roles_result = await self.db.execute(roles_query)
        birthright_roles = roles_result.scalars().all()

        granted = []
        for role in birthright_roles:
            # Check if already assigned
            existing = await self.db.execute(
                select(UserRole).where(
                    and_(
                        UserRole.user_id == user.id,
                        UserRole.role_id == role.id,
                        UserRole.tenant_id == tenant_id,
                        UserRole.deleted_at.is_(None),
                    )
                )
            )
            if not existing.scalar_one_or_none():
                user_role = UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    tenant_id=tenant_id,
                    assigned_by="lifecycle_service",
                    justification="Birthright access",
                )
                self.db.add(user_role)
                granted.append(str(role.id))

        return granted

    async def _remove_role(
        self, user_id: str, role_id: str, tenant_id: str
    ) -> bool:
        """Remove a role assignment."""
        from backend.models.rbac import UserRole

        result = await self.db.execute(
            select(UserRole).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_role = result.scalar_one_or_none()
        if user_role:
            user_role.soft_delete()
            return True
        return False

    async def _grant_role(
        self,
        user_id: str,
        role_id: str,
        tenant_id: str,
        assigned_by: Optional[str],
    ) -> bool:
        """Grant a role to a user."""
        from backend.models.rbac import UserRole

        existing = await self.db.execute(
            select(UserRole).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        if existing.scalar_one_or_none():
            return False

        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            assigned_by=assigned_by or "lifecycle_service",
            justification="Lifecycle event: mover",
        )
        self.db.add(user_role)
        return True

    async def _revoke_all_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user."""
        from backend.models.user import Session

        result = await self.db.execute(
            select(Session).where(
                and_(Session.user_id == user_id, Session.is_active == True)  # noqa: E712
            )
        )
        sessions = result.scalars().all()
        for session in sessions:
            session.is_active = False

        # Also blacklist tokens in Redis
        try:
            from backend.utils.redis_client import redis_client
            for session in sessions:
                # Invalidate user cache
                await redis_client.invalidate_user_cache(str(user_id))
        except Exception:
            pass

        return len(sessions)

    async def _deprovision_all_roles(self, user_id: str, tenant_id: str) -> int:
        """Remove all role assignments for a user."""
        from backend.models.rbac import UserRole

        result = await self.db.execute(
            select(UserRole).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_roles = result.scalars().all()
        for ur in user_roles:
            ur.soft_delete()
        return len(user_roles)

    async def _terminate_pam_sessions(self, user_id: str, tenant_id: str) -> int:
        """Terminate all PAM sessions for a user."""
        from backend.models.pam import PAMSession

        result = await self.db.execute(
            select(PAMSession).where(
                and_(
                    PAMSession.user_id == user_id,
                    PAMSession.tenant_id == tenant_id,
                    PAMSession.status == "active",
                )
            )
        )
        sessions = result.scalars().all()
        now = datetime.now(timezone.utc)
        for session in sessions:
            session.status = "terminated"
            session.terminated_at = now
        return len(sessions)

    async def _send_welcome_notification(
        self, user: User, tenant_id: str, is_rehire: bool = False
    ) -> None:
        """Send welcome notification to a new user."""
        from backend.models.notification import Notification

        title = "Welcome back!" if is_rehire else "Welcome to the platform!"
        message = (
            f"{'Welcome back' if is_rehire else 'Welcome'}, {user.first_name or user.email}! "
            "Your account has been set up. Please log in to review your access."
        )
        notification = Notification(
            tenant_id=tenant_id,
            user_id=user.id,
            notification_type="welcome",
            title=title,
            message=message,
        )
        self.db.add(notification)

    async def _notify_it_hr_leaver(
        self, user: User, tenant_id: str, exit_date: datetime
    ) -> None:
        """Notify IT admins and HR about a leaver."""
        from backend.models.notification import Notification
        from backend.models.rbac import Role, UserRole

        # Find tenant admins
        admin_roles_result = await self.db.execute(
            select(Role).where(
                and_(
                    Role.tenant_id == tenant_id,
                    Role.name.in_(["Tenant Admin", "IT Admin", "HR"]),
                    Role.deleted_at.is_(None),
                )
            )
        )
        admin_roles = admin_roles_result.scalars().all()
        admin_role_ids = [r.id for r in admin_roles]

        if not admin_role_ids:
            return

        admin_users_result = await self.db.execute(
            select(UserRole.user_id).where(
                and_(
                    UserRole.role_id.in_(admin_role_ids),
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        admin_user_ids = {str(r[0]) for r in admin_users_result.all()}

        # Also include is_superuser users
        tenant_admins_result = await self.db.execute(
            select(User.id).where(
                and_(
                    User.tenant_id == tenant_id,
                    User.is_superuser == True,  # noqa: E712
                    User.deleted_at.is_(None),
                )
            )
        )
        for (aid,) in tenant_admins_result.all():
            admin_user_ids.add(str(aid))

        for admin_id in admin_user_ids:
            notification = Notification(
                tenant_id=tenant_id,
                user_id=admin_id,
                notification_type="leaver_alert",
                title=f"User Offboarding: {user.email}",
                message=(
                    f"User {user.email} ({user.first_name} {user.last_name}) "
                    f"is leaving the organization. Exit date: {exit_date.strftime('%Y-%m-%d')}. "
                    "All access has been revoked."
                ),
                reference_type="user",
                reference_id=user.id,
            )
            self.db.add(notification)

    async def _audit_lifecycle(
        self,
        user_id: str,
        tenant_id: str,
        action: str,
        triggered_by: Optional[str],
        details: Dict[str, Any],
    ) -> None:
        """Log a lifecycle event to the audit log."""
        try:
            from backend.audit.audit_logger import audit_logger

            await audit_logger.log(
                self.db,
                tenant_id=tenant_id,
                user_id=triggered_by,
                action=action,
                resource_type="user",
                resource_id=user_id,
                details=details,
                risk_level="medium",
            )
        except Exception as e:
            logger.error("Failed to write lifecycle audit log: %s", e)
