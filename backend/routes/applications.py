"""
Application management routes for the IGA platform.
Handles CRUD for applications, entitlements, user access, and connector health.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_permission
from backend.utils.audit import log_action
from backend.models.user import User
from backend.models.application import Application
from backend.models.entitlement import Entitlement, UserEntitlement
from backend.models.connector import Connector

router = APIRouter(prefix="/applications", tags=["Applications"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ApplicationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    type: str = Field("saas", pattern="^(saas|on_premise|cloud|legacy|custom)$")
    category: Optional[str] = None
    owner_id: Optional[str] = None
    connector_id: Optional[str] = None
    logo_url: Optional[str] = None
    auth_type: str = Field("saml", pattern="^(saml|oidc|oauth2|ldap|scim|api_key|custom)$")
    risk_level: str = Field("medium", pattern="^(low|medium|high|critical)$")
    metadata: Optional[Dict[str, Any]] = None
    is_active: bool = True

class ApplicationUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_id: Optional[str] = None
    logo_url: Optional[str] = None
    risk_level: Optional[str] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

class EntitlementCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    entitlement_type: str = Field("permission", pattern="^(permission|group|role|profile|license)$")
    external_id: Optional[str] = None
    risk_level: str = Field("low", pattern="^(low|medium|high|critical)$")
    is_requestable: bool = True
    requires_approval: bool = True
    metadata: Optional[Dict[str, Any]] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app_to_dict(app: Application) -> dict:
    return {
        "id": str(app.id),
        "name": app.name,
        "description": app.description,
        "type": app.type,
        "category": app.category,
        "owner_id": str(app.owner_id) if app.owner_id else None,
        "connector_id": str(app.connector_id) if app.connector_id else None,
        "logo_url": app.logo_url,
        "auth_type": app.auth_type,
        "risk_level": app.risk_level,
        "is_active": app.is_active,
        "tenant_id": str(app.tenant_id),
        "created_at": app.created_at.isoformat(),
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }

def _ent_to_dict(ent: Entitlement) -> dict:
    return {
        "id": str(ent.id),
        "name": ent.name,
        "description": ent.description,
        "entitlement_type": ent.entitlement_type,
        "external_id": ent.external_id,
        "risk_level": ent.risk_level,
        "is_requestable": ent.is_requestable,
        "requires_approval": ent.requires_approval,
        "application_id": str(ent.application_id),
        "created_at": ent.created_at.isoformat(),
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = None,
    type: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_permission("applications:read")),
    db: AsyncSession = Depends(get_db),
):
    """List applications."""
    query = select(Application).where(Application.tenant_id == current_user.tenant_id)
    count_query = select(func.count(Application.id)).where(Application.tenant_id == current_user.tenant_id)

    if search:
        filt = or_(Application.name.ilike(f"%{search}%"), Application.description.ilike(f"%{search}%"))
        query = query.where(filt)
        count_query = count_query.where(filt)
    if type:
        query = query.where(Application.type == type)
        count_query = count_query.where(Application.type == type)
    if is_active is not None:
        query = query.where(Application.is_active == is_active)
        count_query = count_query.where(Application.is_active == is_active)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(Application.name).offset((page - 1) * page_size).limit(page_size)
    )
    apps = result.scalars().all()

    return {
        "items": [_app_to_dict(a) for a in apps],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("applications:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new application."""
    existing = await db.execute(
        select(Application).where(
            and_(Application.name == body.name, Application.tenant_id == current_user.tenant_id)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application name already exists")

    app = Application(
        name=body.name,
        description=body.description,
        type=body.type,
        category=body.category,
        owner_id=body.owner_id,
        connector_id=body.connector_id,
        logo_url=body.logo_url,
        auth_type=body.auth_type,
        risk_level=body.risk_level,
        is_active=body.is_active,
        app_metadata=body.metadata,
        tenant_id=current_user.tenant_id,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "application_created", "application", str(app.id), {"name": app.name}
    )
    return _app_to_dict(app)


@router.get("/{app_id}")
async def get_application(
    app_id: str,
    current_user: User = Depends(require_permission("applications:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get application details."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    # Count entitlements and users
    ent_count = (await db.execute(
        select(func.count(Entitlement.id)).where(Entitlement.application_id == app_id)
    )).scalar()

    user_count = (await db.execute(
        select(func.count(func.distinct(UserEntitlement.user_id)))
        .join(Entitlement, UserEntitlement.entitlement_id == Entitlement.id)
        .where(
            and_(
                Entitlement.application_id == app_id,
                UserEntitlement.revoked_at.is_(None),
            )
        )
    )).scalar()

    data = _app_to_dict(app)
    data["entitlement_count"] = ent_count
    data["user_count"] = user_count
    data["app_metadata"] = app.app_metadata or {}
    return data


@router.put("/{app_id}")
async def update_application(
    app_id: str,
    body: ApplicationUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("applications:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    update_data = body.dict(exclude_unset=True)
    if "metadata" in update_data:
        update_data["app_metadata"] = update_data.pop("metadata")

    for key, value in update_data.items():
        setattr(app, key, value)
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "application_updated", "application", app_id, {"changes": update_data}
    )
    return _app_to_dict(app)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("applications:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    ent_count = (await db.execute(
        select(func.count(Entitlement.id)).where(Entitlement.application_id == app_id)
    )).scalar()
    if ent_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application has {ent_count} entitlements. Remove them first.",
        )

    await db.delete(app)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "application_deleted", "application", app_id, {"name": app.name}
    )


@router.get("/{app_id}/entitlements")
async def list_app_entitlements(
    app_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    current_user: User = Depends(require_permission("applications:read")),
    db: AsyncSession = Depends(get_db),
):
    """List entitlements for an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    query = select(Entitlement).where(Entitlement.application_id == app_id)
    count_query = select(func.count(Entitlement.id)).where(Entitlement.application_id == app_id)

    if search:
        filt = or_(Entitlement.name.ilike(f"%{search}%"), Entitlement.description.ilike(f"%{search}%"))
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = (await db.execute(count_query)).scalar()
    ent_result = await db.execute(
        query.order_by(Entitlement.name).offset((page - 1) * page_size).limit(page_size)
    )
    entitlements = ent_result.scalars().all()

    return {
        "items": [_ent_to_dict(e) for e in entitlements],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{app_id}/entitlements", status_code=status.HTTP_201_CREATED)
async def create_entitlement(
    app_id: str,
    body: EntitlementCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("applications:update")),
    db: AsyncSession = Depends(get_db),
):
    """Create an entitlement for an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    existing = await db.execute(
        select(Entitlement).where(
            and_(Entitlement.application_id == app_id, Entitlement.name == body.name)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entitlement name already exists for this app")

    ent = Entitlement(
        name=body.name,
        description=body.description,
        entitlement_type=body.entitlement_type,
        external_id=body.external_id,
        risk_level=body.risk_level,
        is_requestable=body.is_requestable,
        requires_approval=body.requires_approval,
        application_id=app_id,
        ent_metadata=body.metadata,
    )
    db.add(ent)
    await db.commit()
    await db.refresh(ent)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "entitlement_created", "entitlement", str(ent.id),
        {"name": ent.name, "app_id": app_id}
    )
    return _ent_to_dict(ent)


@router.get("/{app_id}/users")
async def list_app_users(
    app_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_permission("applications:read")),
    db: AsyncSession = Depends(get_db),
):
    """List users with access to an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    query = (
        select(User, func.count(UserEntitlement.id).label("entitlement_count"))
        .join(UserEntitlement, User.id == UserEntitlement.user_id)
        .join(Entitlement, UserEntitlement.entitlement_id == Entitlement.id)
        .where(
            and_(
                Entitlement.application_id == app_id,
                UserEntitlement.revoked_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
        .group_by(User.id)
    )

    count_q = (
        select(func.count(func.distinct(User.id)))
        .join(UserEntitlement, User.id == UserEntitlement.user_id)
        .join(Entitlement, UserEntitlement.entitlement_id == Entitlement.id)
        .where(
            and_(
                Entitlement.application_id == app_id,
                UserEntitlement.revoked_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
    )
    total = (await db.execute(count_q)).scalar()

    users_result = await db.execute(
        query.order_by(User.last_name, User.first_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = users_result.all()

    return {
        "items": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "department": u.department,
                "status": u.status,
                "entitlement_count": ec,
            }
            for u, ec in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{app_id}/health")
async def get_app_health(
    app_id: str,
    current_user: User = Depends(require_permission("applications:read")),
    db: AsyncSession = Depends(get_db),
):
    """Check connector health for an application."""
    result = await db.execute(
        select(Application).where(
            and_(Application.id == app_id, Application.tenant_id == current_user.tenant_id)
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if not app.connector_id:
        return {
            "app_id": app_id,
            "connector_id": None,
            "status": "no_connector",
            "message": "No connector configured for this application",
        }

    connector_result = await db.execute(
        select(Connector).where(Connector.id == app.connector_id)
    )
    connector = connector_result.scalar_one_or_none()
    if not connector:
        return {
            "app_id": app_id,
            "connector_id": str(app.connector_id),
            "status": "connector_not_found",
            "message": "Connector not found",
        }

    return {
        "app_id": app_id,
        "connector_id": str(connector.id),
        "connector_name": connector.name,
        "connector_type": connector.connector_type,
        "status": connector.health_status or "unknown",
        "last_sync_at": connector.last_sync_at.isoformat() if connector.last_sync_at else None,
        "last_health_check": connector.last_health_check.isoformat() if connector.last_health_check else None,
        "error_message": connector.last_error,
    }
