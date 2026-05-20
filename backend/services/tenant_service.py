import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.tenant import Tenant, TenantBranding, TenantUsageMetering
from backend.models.user import User

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


class TenantService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_tenant(
        self,
        data: Any,  # Can be a Pydantic model or dict
        created_by: str,
    ) -> Tenant:
        """
        Create a new tenant with:
        - Default branding record
        - Default system roles (Admin, User, Read-Only)
        - Default notification templates
        - Admin user (if admin email provided in data)
        """
        # Accept both dict and pydantic model
        if hasattr(data, "model_dump"):
            data_dict = data.model_dump()
        elif hasattr(data, "dict"):
            data_dict = data.dict()
        else:
            data_dict = dict(data)

        name = data_dict["name"]
        slug = data_dict.get("slug") or _slugify(name)
        domain = data_dict.get("domain")
        plan = data_dict.get("plan", "free")
        max_users = data_dict.get("max_users", 100)

        # Ensure slug is unique
        base_slug = slug
        suffix = 0
        while True:
            existing = await self.db.execute(
                select(Tenant).where(Tenant.slug == slug)
            )
            if not existing.scalar_one_or_none():
                break
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        tenant = Tenant(
            name=name,
            slug=slug,
            domain=domain,
            status="trial",
            plan=plan,
            max_users=max_users,
            settings={
                "created_by": created_by,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.db.add(tenant)
        await self.db.flush()

        # Create default branding
        branding = TenantBranding(
            tenant_id=tenant.id,
            company_name=name,
        )
        self.db.add(branding)

        # Create default roles
        await self._create_default_roles(tenant.id)

        # Create default notification templates
        await self._create_default_notification_templates(tenant.id)

        # Create admin user if email provided
        admin_email = data_dict.get("admin_email")
        if admin_email:
            await self._create_admin_user(tenant.id, admin_email, created_by)

        await self.db.commit()
        await self.db.refresh(tenant)
        logger.info("Created tenant %s (slug=%s)", tenant.id, slug)
        return tenant

    async def _create_default_roles(self, tenant_id) -> None:
        """Create standard IGA roles for a new tenant."""
        from backend.models.rbac import Role

        default_roles = [
            {
                "name": "Tenant Admin",
                "description": "Full administrative access",
                "role_type": "business",
                "is_privileged": True,
                "risk_level": "high",
            },
            {
                "name": "User",
                "description": "Standard user access",
                "role_type": "business",
                "is_privileged": False,
                "risk_level": "low",
            },
            {
                "name": "Read Only",
                "description": "Read-only access to resources",
                "role_type": "business",
                "is_privileged": False,
                "risk_level": "low",
            },
            {
                "name": "Reviewer",
                "description": "Can review and certify access",
                "role_type": "business",
                "is_privileged": False,
                "risk_level": "low",
            },
        ]
        for role_data in default_roles:
            role = Role(
                tenant_id=tenant_id,
                **role_data,
            )
            self.db.add(role)

    async def _create_default_notification_templates(self, tenant_id) -> None:
        """Create default notification templates for a new tenant."""
        from backend.models.notification import NotificationTemplate

        templates = [
            {
                "template_type": "access_request_submitted",
                "subject": "Access Request Submitted - {{request_id}}",
                "body_html": "<p>Your access request has been submitted for review.</p>",
                "body_text": "Your access request has been submitted for review.",
                "variables": ["request_id", "user_name", "access_type"],
            },
            {
                "template_type": "access_request_approved",
                "subject": "Access Request Approved",
                "body_html": "<p>Your access request has been approved.</p>",
                "body_text": "Your access request has been approved.",
                "variables": ["request_id", "user_name", "approved_by"],
            },
            {
                "template_type": "access_request_rejected",
                "subject": "Access Request Rejected",
                "body_html": "<p>Your access request has been rejected.</p>",
                "body_text": "Your access request has been rejected.",
                "variables": ["request_id", "user_name", "reason"],
            },
            {
                "template_type": "certification_started",
                "subject": "Certification Campaign: {{campaign_name}}",
                "body_html": "<p>A new certification campaign requires your attention.</p>",
                "body_text": "A new certification campaign requires your attention.",
                "variables": ["campaign_name", "deadline"],
            },
            {
                "template_type": "welcome",
                "subject": "Welcome to {{company_name}}",
                "body_html": "<p>Welcome to the IGA platform.</p>",
                "body_text": "Welcome to the IGA platform.",
                "variables": ["user_name", "company_name", "login_url"],
            },
        ]
        for tmpl in templates:
            template = NotificationTemplate(
                tenant_id=tenant_id,
                **tmpl,
                is_active=True,
            )
            self.db.add(template)

    async def _create_admin_user(
        self, tenant_id, admin_email: str, created_by: str
    ) -> User:
        """Create the initial admin user for a tenant."""
        user = User(
            tenant_id=tenant_id,
            email=admin_email,
            username=admin_email,
            status="active",
            is_tenant_admin=True,
            email_verified=True,
            created_by=created_by,
        )
        self.db.add(user)
        return user

    async def suspend_tenant(
        self, tenant_id: str, reason: Optional[str], by: str
    ) -> Tenant:
        """Suspend a tenant (blocks all access)."""
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        tenant.status = "suspended"
        settings = dict(tenant.settings or {})
        settings.update(
            {
                "suspension_reason": reason,
                "suspended_by": by,
                "suspended_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        tenant.settings = settings
        await self.db.commit()
        logger.info("Suspended tenant %s by %s", tenant_id, by)
        return tenant

    async def activate_tenant(self, tenant_id: str, by: str) -> Tenant:
        """Activate or re-activate a tenant."""
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        tenant.status = "active"
        settings = dict(tenant.settings or {})
        settings.update(
            {
                "activated_by": by,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        tenant.settings = settings
        await self.db.commit()
        logger.info("Activated tenant %s by %s", tenant_id, by)
        return tenant

    async def get_tenant_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Return comprehensive stats for a tenant."""
        from backend.models.sod import SODViolation

        user_count = (
            await self.db.execute(
                select(func.count(User.id)).where(
                    and_(
                        User.tenant_id == tenant_id,
                        User.deleted_at.is_(None),
                    )
                )
            )
        ).scalar() or 0

        active_users = (
            await self.db.execute(
                select(func.count(User.id)).where(
                    and_(
                        User.tenant_id == tenant_id,
                        User.status == "active",
                        User.deleted_at.is_(None),
                    )
                )
            )
        ).scalar() or 0

        open_violations = (
            await self.db.execute(
                select(func.count(SODViolation.id)).where(
                    and_(
                        SODViolation.tenant_id == tenant_id,
                        SODViolation.status == "open",
                    )
                )
            )
        ).scalar() or 0

        total_requests = 0
        try:
            from backend.models.access_request import AccessRequest

            total_requests = (
                await self.db.execute(
                    select(func.count(AccessRequest.id)).where(
                        AccessRequest.tenant_id == tenant_id
                    )
                )
            ).scalar() or 0
        except Exception:
            pass

        return {
            "tenant_id": str(tenant_id),
            "user_count": user_count,
            "active_users": active_users,
            "total_access_requests": total_requests,
            "open_sod_violations": open_violations,
        }

    async def get_usage_metering(
        self, tenant_id: str, period: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return usage metering data for a tenant."""
        query = (
            select(TenantUsageMetering)
            .where(TenantUsageMetering.tenant_id == tenant_id)
            .order_by(TenantUsageMetering.period_start.desc())
            .limit(12)
        )
        rows = await self.db.execute(query)
        records = rows.scalars().all()

        # Get current user count
        current_users = (
            await self.db.execute(
                select(func.count(User.id)).where(
                    and_(
                        User.tenant_id == tenant_id,
                        User.status == "active",
                        User.deleted_at.is_(None),
                    )
                )
            )
        ).scalar() or 0

        tenant_result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = tenant_result.scalar_one_or_none()

        return {
            "tenant_id": str(tenant_id),
            "plan": tenant.plan if tenant else "unknown",
            "max_users": tenant.max_users if tenant else 0,
            "current_active_users": current_users,
            "user_utilization_pct": round(
                current_users / tenant.max_users * 100 if tenant and tenant.max_users > 0 else 0, 1
            ),
            "usage_history": [r.to_dict() for r in records],
        }

    async def list_tenants(
        self,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all tenants with pagination and optional search."""
        query = select(Tenant)
        if search:
            query = query.where(
                Tenant.name.ilike(f"%{search}%") | Tenant.slug.ilike(f"%{search}%")
            )
        if status_filter:
            query = query.where(Tenant.status == status_filter)

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar() or 0

        query = (
            query.order_by(Tenant.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = await self.db.execute(query)
        tenants = rows.scalars().all()

        return {
            "items": [t.to_dict() for t in tenants],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
