"""
User management routes for the IGA platform.
Handles CRUD, lifecycle operations, bulk operations, and user analytics.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_, text
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime, timezone
import csv
import io
import uuid
import secrets
import hashlib

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_permission, get_password_hash
from backend.utils.audit import log_action
from backend.models.user import User, Session as UserSession, LoginHistory
from backend.models.rbac import Role, UserRole
from backend.models.application import Entitlement, UserEntitlement
from backend.models.access_request import AccessRequest
from backend.models.audit import AuditLog
from backend.models.risk import RiskScore
from backend.utils.email import send_email
from backend.utils.storage import upload_file_to_storage

router = APIRouter(prefix="/users", tags=["Users"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class UserCreateRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    display_name: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    manager_id: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    employee_id: Optional[str] = None
    send_invite: bool = True
    role_ids: List[str] = []

class UserUpdateRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_name: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    manager_id: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    employee_id: Optional[str] = None

class AdminResetPasswordRequest(BaseModel):
    new_password: Optional[str] = None
    send_email: bool = True
    force_change_on_login: bool = True

class LockUserRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    duration_minutes: Optional[int] = None

class SuspendUserRequest(BaseModel):
    reason: str = Field(..., min_length=1)

class OffboardRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    effective_date: Optional[datetime] = None
    revoke_access_immediately: bool = True

class BulkImportResponse(BaseModel):
    total: int
    created: int
    skipped: int
    errors: List[dict]

# ---------------------------------------------------------------------------
# Helper: build user dict
# ---------------------------------------------------------------------------

def _user_to_dict(user: User, include_sensitive: bool = False) -> dict:
    d = {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name,
        "full_name": user.full_name or f"{user.first_name or ''} {user.last_name or ''}".strip(),
        "phone": user.phone,
        "employee_id": user.employee_id,
        "is_active": user.is_active,
        "is_locked": user.is_locked,
        "avatar_url": user.avatar_url,
        "mfa_enabled": user.mfa_enabled,
        "email_verified": user.email_verified,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "tenant_id": str(user.tenant_id),
        "manager_id": str(user.manager_id) if user.manager_id else None,
    }
    if include_sensitive:
        d["failed_login_attempts"] = user.failed_login_attempts
        d["locked_until"] = user.locked_until.isoformat() if user.locked_until else None
    return d

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    status: Optional[str] = None,
    department: Optional[str] = None,
    role_id: Optional[str] = None,
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """List users with pagination and filtering."""
    query = select(User).where(
        and_(User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
    )
    count_query = select(func.count(User.id)).where(
        and_(User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
    )

    if search:
        search_filter = or_(
            User.email.ilike(f"%{search}%"),
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
            User.display_name.ilike(f"%{search}%"),
            User.employee_id.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if status:
        if status in ("active",):
            query = query.where(User.is_active == True)
            count_query = count_query.where(User.is_active == True)
        elif status in ("inactive", "suspended"):
            query = query.where(User.is_active == False)
            count_query = count_query.where(User.is_active == False)
        elif status == "locked":
            query = query.where(User.is_locked == True)
            count_query = count_query.where(User.is_locked == True)

    if role_id:
        query = query.join(UserRole, User.id == UserRole.user_id).where(UserRole.role_id == role_id)
        count_query = count_query.join(UserRole, User.id == UserRole.user_id).where(UserRole.role_id == role_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "items": [_user_to_dict(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)."""
    result = await db.execute(
        select(User).where(
            and_(User.email == body.email.lower(), User.tenant_id == current_user.tenant_id)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered in this tenant")

    temp_password = secrets.token_urlsafe(16)
    new_user = User(
        email=body.email.lower(),
        hashed_password=get_password_hash(temp_password),
        first_name=body.first_name,
        last_name=body.last_name,
        display_name=body.display_name or f"{body.first_name} {body.last_name}",
        manager_id=body.manager_id,
        phone=body.phone,
        employee_id=body.employee_id,
        tenant_id=current_user.tenant_id,
        is_active=True,
        is_locked=False,
        email_verified=False,
    )
    db.add(new_user)
    await db.flush()

    # Assign roles
    for role_id in body.role_ids:
        result_r = await db.execute(
            select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
        )
        role = result_r.scalar_one_or_none()
        if role:
            db.add(UserRole(user_id=new_user.id, role_id=role.id, assigned_by=current_user.id))

    await db.commit()
    await db.refresh(new_user)

    if body.send_invite:
        try:
            background_tasks.add_task(
                send_email,
                to=new_user.email,
                subject="Welcome to IGA Platform",
                template="user_invitation",
                context={"user": new_user.first_name, "temp_password": temp_password},
            )
        except Exception:
            pass

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_created", "user", str(new_user.id),
        {"email": new_user.email, "created_by": str(current_user.id)}
    )
    return _user_to_dict(new_user)


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get user details with roles, entitlements, and risk score."""
    result = await db.execute(
        select(User)
        .where(and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None)))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Get entitlements
    ent_result = await db.execute(
        select(UserEntitlement)
        .where(and_(UserEntitlement.user_id == user.id, UserEntitlement.revoked_at.is_(None)))
        .options(selectinload(UserEntitlement.entitlement))
    )
    entitlements = ent_result.scalars().all()

    # Get risk score
    risk_result = await db.execute(
        select(RiskScore).where(RiskScore.user_id == user.id).order_by(RiskScore.calculated_at.desc()).limit(1)
    )
    risk = risk_result.scalar_one_or_none()

    data = _user_to_dict(user, include_sensitive=True)
    data["roles"] = [{"id": str(r.id), "name": r.name, "description": r.description} for r in user.roles]
    data["entitlements"] = [
        {
            "id": str(ue.id),
            "entitlement_id": str(ue.entitlement_id),
            "name": ue.entitlement.name if ue.entitlement else None,
            "granted_at": ue.granted_at.isoformat() if ue.granted_at else None,
        }
        for ue in entitlements
    ]
    data["risk_score"] = {
        "score": risk.score if risk else 0,
        "level": risk.level if risk else "low",
        "calculated_at": risk.calculated_at.isoformat() if risk else None,
    }
    return data


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_data = _user_to_dict(user)
    update_data = body.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_updated", "user", user_id,
        {"changes": update_data, "old": old_data}
    )
    return _user_to_dict(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_deleted", "user", user_id, {"email": user.email}
    )


@router.post("/{user_id}/lock")
async def lock_user(
    user_id: str,
    body: LockUserRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Lock a user account."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_locked = True
    from datetime import timedelta
    if body.duration_minutes:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=body.duration_minutes)
    await db.commit()

    # Revoke all active sessions
    await db.execute(
        update(UserSession)
        .where(and_(UserSession.user_id == user.id, UserSession.is_active == True))
        .values(is_active=False)
    )
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_locked", "user", user_id, {"reason": body.reason}
    )
    return {"message": "User locked", "user_id": user_id}


@router.post("/{user_id}/unlock")
async def unlock_user(
    user_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Unlock a user account."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_locked = False
    user.locked_until = None
    user.failed_login_attempts = 0
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_unlocked", "user", user_id, {}
    )
    return {"message": "User unlocked", "user_id": user_id}


@router.post("/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    body: SuspendUserRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Suspend a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    await db.commit()

    await db.execute(
        update(UserSession)
        .where(and_(UserSession.user_id == user.id, UserSession.is_active == True))
        .values(is_active=False)
    )
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_suspended", "user", user_id, {"reason": body.reason}
    )
    return {"message": "User suspended", "user_id": user_id}


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Activate a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = True
    user.is_locked = False
    user.locked_until = None
    user.failed_login_attempts = 0
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_activated", "user", user_id, {}
    )
    return {"message": "User activated", "user_id": user_id}


@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    body: AdminResetPasswordRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Admin reset user password."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    new_password = body.new_password or secrets.token_urlsafe(16)
    user.hashed_password = get_password_hash(new_password)
    user.force_password_change = body.force_change_on_login
    user.password_changed_at = datetime.now(timezone.utc)
    await db.commit()

    if body.send_email:
        background_tasks.add_task(
            send_email,
            to=user.email,
            subject="Your password has been reset",
            template="admin_password_reset",
            context={"user": user.first_name, "temp_password": new_password},
        )

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "admin_password_reset", "user", user_id,
        {"admin": str(current_user.id)}
    )
    return {"message": "Password reset successfully", "temp_password": new_password if not body.send_email else None}


@router.get("/{user_id}/roles")
async def get_user_roles(
    user_id: str,
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """List roles assigned to a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result_roles = await db.execute(
        select(Role, UserRole)
        .join(UserRole, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )
    rows = result_roles.all()
    return {
        "roles": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "assigned_at": ur.assigned_at.isoformat() if ur.assigned_at else None,
                "assigned_by": str(ur.assigned_by) if ur.assigned_by else None,
            }
            for r, ur in rows
        ]
    }


@router.get("/{user_id}/entitlements")
async def get_user_entitlements(
    user_id: str,
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """List entitlements for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    ent_result = await db.execute(
        select(UserEntitlement)
        .where(and_(UserEntitlement.user_id == user_id, UserEntitlement.revoked_at.is_(None)))
        .options(selectinload(UserEntitlement.entitlement))
        .order_by(UserEntitlement.granted_at.desc())
    )
    entitlements = ent_result.scalars().all()
    return {
        "entitlements": [
            {
                "id": str(ue.id),
                "entitlement_id": str(ue.entitlement_id),
                "name": ue.entitlement.name if ue.entitlement else None,
                "application": ue.entitlement.application_id if ue.entitlement else None,
                "granted_at": ue.granted_at.isoformat() if ue.granted_at else None,
                "expires_at": ue.expires_at.isoformat() if ue.expires_at else None,
            }
            for ue in entitlements
        ]
    }


@router.get("/{user_id}/access-requests")
async def get_user_access_requests(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get access request history for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    count_q = await db.execute(
        select(func.count(AccessRequest.id)).where(AccessRequest.requester_id == user_id)
    )
    total = count_q.scalar()

    req_result = await db.execute(
        select(AccessRequest)
        .where(AccessRequest.requester_id == user_id)
        .order_by(AccessRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    requests = req_result.scalars().all()

    return {
        "items": [
            {
                "id": str(r.id),
                "status": r.status,
                "resource_type": r.resource_type,
                "resource_id": str(r.resource_id) if r.resource_id else None,
                "justification": r.justification,
                "created_at": r.created_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in requests
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{user_id}/audit-log")
async def get_user_audit_log(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get audit log for a specific user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    count_q = await db.execute(
        select(func.count(AuditLog.id)).where(
            or_(AuditLog.actor_id == user_id, AuditLog.resource_id == user_id)
        )
    )
    total = count_q.scalar()

    log_result = await db.execute(
        select(AuditLog)
        .where(or_(AuditLog.actor_id == user_id, AuditLog.resource_id == user_id))
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = log_result.scalars().all()

    return {
        "items": [
            {
                "id": str(l.id),
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "actor_id": str(l.actor_id) if l.actor_id else None,
                "metadata": l.metadata,
                "ip_address": l.ip_address,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{user_id}/risk-score")
async def get_user_risk_score(
    user_id: str,
    current_user: User = Depends(require_permission("risk:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get risk score details for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    risk_result = await db.execute(
        select(RiskScore)
        .where(RiskScore.user_id == user_id)
        .order_by(RiskScore.calculated_at.desc())
        .limit(1)
    )
    risk = risk_result.scalar_one_or_none()

    if not risk:
        return {"user_id": user_id, "score": 0, "level": "low", "factors": [], "calculated_at": None}

    return {
        "user_id": user_id,
        "score": risk.score,
        "level": risk.level,
        "factors": risk.factors or [],
        "calculated_at": risk.calculated_at.isoformat(),
        "previous_score": risk.previous_score,
        "trend": "increasing" if risk.score > (risk.previous_score or 0) else "decreasing",
    }


@router.get("/{user_id}/login-history")
async def get_login_history(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get login history for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    count_q = await db.execute(
        select(func.count(LoginHistory.id)).where(LoginHistory.user_id == user_id)
    )
    total = count_q.scalar()

    hist_result = await db.execute(
        select(LoginHistory)
        .where(LoginHistory.user_id == user_id)
        .order_by(LoginHistory.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    history = hist_result.scalars().all()

    return {
        "items": [
            {
                "id": str(h.id),
                "ip_address": h.ip_address,
                "user_agent": h.user_agent,
                "success": h.success,
                "failure_reason": h.failure_reason,
                "created_at": h.created_at.isoformat(),
            }
            for h in history
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get active sessions for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    sess_result = await db.execute(
        select(UserSession).where(
            and_(
                UserSession.user_id == user_id,
                UserSession.revoked == False,
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        ).order_by(UserSession.created_at.desc())
    )
    sessions = sess_result.scalars().all()

    return {
        "sessions": [
            {
                "id": str(s.id),
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
            }
            for s in sessions
        ]
    }


@router.post("/{user_id}/avatar")
async def upload_avatar(
    user_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload user avatar."""
    # Only allow user to update own avatar or admin
    if str(current_user.id) != user_id:
        require_permission("users:update")(current_user)

    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large (max 5MB)")

    avatar_url = await upload_file_to_storage(
        contents,
        filename=f"avatars/{user_id}/{file.filename}",
        content_type=file.content_type,
    )
    user.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}


@router.post("/bulk/import", response_model=BulkImportResponse)
async def bulk_import_users(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(require_permission("users:create")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk import users from CSV."""
    if file.content_type not in ("text/csv", "application/vnd.ms-excel"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV files are accepted")

    contents = await file.read()
    reader = csv.DictReader(io.StringIO(contents.decode("utf-8-sig")))

    required_fields = {"email", "first_name", "last_name"}
    if not required_fields.issubset(set(reader.fieldnames or [])):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV must contain columns: {required_fields}",
        )

    created = 0
    skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        email = row.get("email", "").strip().lower()
        if not email:
            errors.append({"row": i, "error": "Email is required"})
            continue

        existing = await db.execute(
            select(User).where(
                and_(User.email == email, User.tenant_id == current_user.tenant_id)
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        try:
            temp_password = secrets.token_urlsafe(16)
            new_user = User(
                email=email,
                hashed_password=get_password_hash(temp_password),
                first_name=row.get("first_name", "").strip(),
                last_name=row.get("last_name", "").strip(),
                display_name=row.get("display_name", "").strip() or None,
                department=row.get("department", "").strip() or None,
                job_title=row.get("job_title", "").strip() or None,
                employee_id=row.get("employee_id", "").strip() or None,
                tenant_id=current_user.tenant_id,
                status="active",
                force_password_change=True,
            )
            db.add(new_user)
            await db.flush()
            created += 1
        except Exception as e:
            errors.append({"row": i, "email": email, "error": str(e)})

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "bulk_users_imported", "user", None,
        {"created": created, "skipped": skipped, "errors": len(errors)}
    )

    return BulkImportResponse(
        total=created + skipped + len(errors),
        created=created,
        skipped=skipped,
        errors=errors,
    )


@router.get("/export")
async def export_users(
    current_user: User = Depends(require_permission("users:export")),
    db: AsyncSession = Depends(get_db),
):
    """Export user list as CSV."""
    from fastapi.responses import StreamingResponse
    result = await db.execute(
        select(User).where(
            and_(User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        ).order_by(User.created_at)
    )
    users = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "email", "first_name", "last_name", "department",
        "job_title", "status", "employee_id", "created_at", "last_login_at",
    ])
    for u in users:
        writer.writerow([
            str(u.id), u.email, u.first_name, u.last_name,
            u.department or "", u.job_title or "", u.status,
            u.employee_id or "",
            u.created_at.isoformat(),
            u.last_login_at.isoformat() if u.last_login_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.post("/{user_id}/offboard")
async def offboard_user(
    user_id: str,
    body: OffboardRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger leaver / offboarding workflow for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.revoke_access_immediately:
        user.is_active = False
        # Revoke all sessions
        await db.execute(
            update(UserSession)
            .where(and_(UserSession.user_id == user.id, UserSession.is_active == True))
            .values(is_active=False)
        )
        # Revoke entitlements
        await db.execute(
            update(UserEntitlement)
            .where(and_(UserEntitlement.user_id == user.id, UserEntitlement.status == "active"))
            .values(status="revoked")
        )
        await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "user_offboarding_triggered", "user", user_id,
        {"reason": body.reason, "effective_date": body.effective_date.isoformat() if body.effective_date else None}
    )
    return {"message": "Offboarding workflow triggered", "user_id": user_id}


@router.get("/{user_id}/profile-versions")
async def get_profile_versions(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get profile change history for a user."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    count_q = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(
                AuditLog.resource_id == user_id,
                AuditLog.action == "user_updated",
            )
        )
    )
    total = count_q.scalar()

    log_result = await db.execute(
        select(AuditLog)
        .where(and_(AuditLog.resource_id == user_id, AuditLog.action == "user_updated"))
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = log_result.scalars().all()

    return {
        "items": [
            {
                "id": str(l.id),
                "changed_by": str(l.actor_id) if l.actor_id else None,
                "changes": l.metadata.get("changes") if l.metadata else {},
                "changed_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
