from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.tenant import Tenant, TenantBranding, TenantUsageMetering
from backend.models.user import User
from backend.audit.audit_logger import audit_logger

router = APIRouter(prefix="/tenants", tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str
    slug: str
    domain: Optional[str] = None
    plan: str = "free"
    max_users: int = 100


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    plan: Optional[str] = None
    max_users: Optional[int] = None


class TenantBrandingUpdate(BaseModel):
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    company_name: Optional[str] = None
    custom_domain: Optional[str] = None
    email_footer: Optional[str] = None


class SuspendRequest(BaseModel):
    reason: Optional[str] = None


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_data = getattr(request.state, "user", None)
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = user_data.get("id")
    tenant_id = user_data.get("tenant_id")
    result = await db.execute(
        select(User).where(and_(User.id == user_id, User.tenant_id == tenant_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=403,
            detail="Super-admin access required",
        )
    return current_user


@router.get("/")
async def list_tenants(
    search: Optional[str] = Query(None),
    tenant_status: Optional[str] = Query(None, alias="status"),
    plan: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    query = select(Tenant)
    if search:
        query = query.where(
            Tenant.name.ilike(f"%{search}%") | Tenant.slug.ilike(f"%{search}%")
        )
    if tenant_status:
        query = query.where(Tenant.is_active == (tenant_status == "active"))
    if plan:
        query = query.where(Tenant.plan_tier == plan)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(Tenant.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    tenants = rows.scalars().all()

    return {
        "items": [t.to_dict() for t in tenants],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Tenant with slug '{data.slug}' already exists")

    from backend.services.tenant_service import TenantService
    svc = TenantService(db)
    tenant = await svc.create_tenant(data, created_by=str(current_user.id))

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "tenant.create",
        "tenant",
        str(tenant.id),
        {"name": data.name, "slug": data.slug},
        ip_address=request.client.host if request.client else None,
    )
    return tenant.to_dict()


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant_dict = tenant.to_dict()

    # Load stats
    user_count_result = await db.execute(
        select(func.count(User.id)).where(
            and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    tenant_dict["stats"] = {"user_count": user_count_result.scalar()}

    # Load branding
    branding_result = await db.execute(
        select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
    )
    branding = branding_result.scalar_one_or_none()
    tenant_dict["branding"] = branding.to_dict() if branding else None

    return tenant_dict


@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: UUID,
    data: TenantUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name is not None:
        tenant.name = data.name
    if data.domain is not None:
        tenant.domain = data.domain
    if data.plan is not None:
        tenant.plan_tier = data.plan
    if data.max_users is not None:
        tenant.max_users = data.max_users

    await db.commit()
    return tenant.to_dict()


@router.post("/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: UUID,
    data: SuspendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant.is_active:
        raise HTTPException(status_code=400, detail="Tenant is already suspended")

    tenant.is_active = False
    settings_data = dict(tenant.settings or {})
    settings_data["suspension_reason"] = data.reason
    settings_data["suspended_by"] = str(current_user.id)
    settings_data["suspended_at"] = datetime.now(timezone.utc).isoformat()
    tenant.settings = settings_data
    await db.commit()

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "tenant.suspend",
        "tenant",
        str(tenant_id),
        {"reason": data.reason},
        ip_address=request.client.host if request.client else None,
        risk_level="high",
    )
    return tenant.to_dict()


@router.post("/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.is_active = True
    settings_data = dict(tenant.settings or {})
    settings_data["activated_by"] = str(current_user.id)
    settings_data["activated_at"] = datetime.now(timezone.utc).isoformat()
    tenant.settings = settings_data
    await db.commit()

    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "tenant.activate",
        "tenant",
        str(tenant_id),
        {},
        ip_address=request.client.host if request.client else None,
    )
    return tenant.to_dict()


@router.get("/{tenant_id}/usage")
async def get_tenant_usage(
    tenant_id: UUID,
    period: Optional[str] = Query("current_month"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get usage metering records
    usage_result = await db.execute(
        select(TenantUsageMetering)
        .where(TenantUsageMetering.tenant_id == tenant_id)
        .order_by(desc(TenantUsageMetering.period_start))
        .limit(12)
    )
    usage_records = usage_result.scalars().all()

    return {
        "tenant_id": str(tenant_id),
        "tenant_name": tenant.name,
        "plan": tenant.plan_tier,
        "max_users": tenant.max_users,
        "period": period,
        "usage_history": [u.to_dict() for u in usage_records],
    }


@router.get("/{tenant_id}/stats")
async def get_tenant_stats(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from backend.models.access_request import AccessRequest
    from backend.models.sod import SODViolation

    user_count = (
        await db.execute(
            select(func.count(User.id)).where(
                and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
            )
        )
    ).scalar()

    active_users = (
        await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.tenant_id == tenant_id,
                    User.is_active == True,
                    User.deleted_at.is_(None),
                )
            )
        )
    ).scalar()

    try:
        total_requests = (
            await db.execute(
                select(func.count(AccessRequest.id)).where(
                    AccessRequest.tenant_id == tenant_id
                )
            )
        ).scalar()
    except Exception:
        total_requests = 0

    open_violations = (
        await db.execute(
            select(func.count(SODViolation.id)).where(
                and_(
                    SODViolation.tenant_id == tenant_id,
                    SODViolation.status == "open",
                )
            )
        )
    ).scalar()

    return {
        "tenant_id": str(tenant_id),
        "tenant_name": tenant.name,
        "user_count": user_count,
        "active_users": active_users,
        "total_access_requests": total_requests,
        "open_sod_violations": open_violations,
    }


@router.put("/{tenant_id}/branding")
async def update_tenant_branding(
    tenant_id: UUID,
    data: TenantBrandingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    branding_result = await db.execute(
        select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
    )
    branding = branding_result.scalar_one_or_none()

    if not branding:
        branding = TenantBranding(tenant_id=tenant_id)
        db.add(branding)

    if data.logo_url is not None:
        branding.logo_url = data.logo_url
    if data.favicon_url is not None:
        branding.favicon_url = data.favicon_url
    if data.primary_color is not None:
        branding.primary_color = data.primary_color
    if data.secondary_color is not None:
        branding.secondary_color = data.secondary_color
    if data.company_name is not None:
        branding.company_name = data.company_name
    if data.custom_domain is not None:
        branding.custom_domain = data.custom_domain
    if data.email_footer is not None:
        branding.email_footer = data.email_footer

    await db.commit()
    await db.refresh(branding)
    return branding.to_dict()


@router.get("/{tenant_id}/users")
async def list_tenant_users(
    tenant_id: UUID,
    search: Optional[str] = Query(None),
    user_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    query = select(User).where(
        and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )
    if search:
        query = query.where(
            User.email.ilike(f"%{search}%")
            | User.first_name.ilike(f"%{search}%")
            | User.last_name.ilike(f"%{search}%")
        )
    if user_status:
        if user_status == "active":
            query = query.where(User.is_active == True)
        elif user_status in ("inactive", "suspended"):
            query = query.where(User.is_active == False)
        elif user_status == "locked":
            query = query.where(User.is_locked == True)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(User.email).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    users = rows.scalars().all()

    return {
        "items": [u.to_dict() for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
