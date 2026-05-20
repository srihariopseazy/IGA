"""
RBAC routes for the IGA platform.
Handles roles, permissions, assignments, and SoD analysis.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_permission
from backend.utils.audit import log_action
from backend.models.user import User
from backend.models.role import Role, Permission, RolePermission, UserRole
from backend.models.sod import SoDPolicy, SoDConflict

router = APIRouter(tags=["Roles & Permissions"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    type: str = Field("custom", pattern="^(system|custom|business|it)$")
    is_requestable: bool = True
    requires_approval: bool = True
    risk_level: str = Field("low", pattern="^(low|medium|high|critical)$")
    permission_ids: List[str] = []

class RoleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_requestable: Optional[bool] = None
    requires_approval: Optional[bool] = None
    risk_level: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")

class PermissionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    resource: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    application_id: Optional[str] = None
    risk_level: str = Field("low", pattern="^(low|medium|high|critical)$")

class PermissionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    risk_level: Optional[str] = None

class AddPermissionsRequest(BaseModel):
    permission_ids: List[str] = Field(..., min_items=1)

class AssignRoleRequest(BaseModel):
    user_ids: List[str] = Field(..., min_items=1)
    justification: Optional[str] = None
    expires_at: Optional[datetime] = None

class RoleMiningRequest(BaseModel):
    department: Optional[str] = None
    min_users: int = Field(5, ge=2)
    similarity_threshold: float = Field(0.8, ge=0.0, le=1.0)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _role_to_dict(role: Role) -> dict:
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description,
        "type": role.type,
        "is_requestable": role.is_requestable,
        "requires_approval": role.requires_approval,
        "risk_level": role.risk_level,
        "tenant_id": str(role.tenant_id),
        "created_at": role.created_at.isoformat(),
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
    }

def _permission_to_dict(p: Permission) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "resource": p.resource,
        "action": p.action,
        "application_id": str(p.application_id) if p.application_id else None,
        "risk_level": p.risk_level,
        "created_at": p.created_at.isoformat(),
    }

# ---------------------------------------------------------------------------
# Role Endpoints
# ---------------------------------------------------------------------------

@router.get("/roles")
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    type: Optional[str] = None,
    risk_level: Optional[str] = None,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """List roles with pagination."""
    query = select(Role).where(Role.tenant_id == current_user.tenant_id)
    count_query = select(func.count(Role.id)).where(Role.tenant_id == current_user.tenant_id)

    if search:
        filt = or_(Role.name.ilike(f"%{search}%"), Role.description.ilike(f"%{search}%"))
        query = query.where(filt)
        count_query = count_query.where(filt)
    if type:
        query = query.where(Role.type == type)
        count_query = count_query.where(Role.type == type)
    if risk_level:
        query = query.where(Role.risk_level == risk_level)
        count_query = count_query.where(Role.risk_level == risk_level)

    total = (await db.execute(count_query)).scalar()

    # Member counts subquery
    member_count_subq = (
        select(UserRole.role_id, func.count(UserRole.user_id).label("member_count"))
        .group_by(UserRole.role_id)
        .subquery()
    )

    query = (
        query.outerjoin(member_count_subq, Role.id == member_count_subq.c.role_id)
        .add_columns(func.coalesce(member_count_subq.c.member_count, 0).label("member_count"))
        .order_by(Role.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    rows = result.all()

    return {
        "items": [
            {**_role_to_dict(r), "member_count": mc}
            for r, mc in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new role."""
    existing = await db.execute(
        select(Role).where(and_(Role.name == body.name, Role.tenant_id == current_user.tenant_id))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")

    role = Role(
        name=body.name,
        description=body.description,
        type=body.type,
        is_requestable=body.is_requestable,
        requires_approval=body.requires_approval,
        risk_level=body.risk_level,
        tenant_id=current_user.tenant_id,
    )
    db.add(role)
    await db.flush()

    for perm_id in body.permission_ids:
        perm = await db.execute(select(Permission).where(Permission.id == perm_id))
        if perm.scalar_one_or_none():
            db.add(RolePermission(role_id=role.id, permission_id=perm_id))

    await db.commit()
    await db.refresh(role)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_created", "role", str(role.id), {"name": role.name}
    )
    return _role_to_dict(role)


@router.get("/roles/{role_id}")
async def get_role(
    role_id: str,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get role with permissions and member count."""
    result = await db.execute(
        select(Role)
        .where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
        .options(selectinload(Role.permissions))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    member_count_q = await db.execute(
        select(func.count(UserRole.user_id)).where(UserRole.role_id == role_id)
    )
    member_count = member_count_q.scalar()

    data = _role_to_dict(role)
    data["permissions"] = [_permission_to_dict(p) for p in role.permissions]
    data["member_count"] = member_count
    return data


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str,
    body: RoleUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update a role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.type == "system":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify system roles")

    update_data = body.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(role, key, value)
    role.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_updated", "role", role_id, {"changes": update_data}
    )
    return _role_to_dict(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role.type == "system":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete system roles")

    member_count_q = await db.execute(
        select(func.count(UserRole.user_id)).where(UserRole.role_id == role_id)
    )
    if member_count_q.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete role with active members. Remove all members first.",
        )

    await db.delete(role)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_deleted", "role", role_id, {"name": role.name}
    )


@router.get("/roles/{role_id}/permissions")
async def list_role_permissions(
    role_id: str,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """List permissions assigned to a role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    perm_result = await db.execute(
        select(Permission)
        .join(RolePermission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.resource, Permission.action)
    )
    permissions = perm_result.scalars().all()
    return {"permissions": [_permission_to_dict(p) for p in permissions]}


@router.post("/roles/{role_id}/permissions")
async def add_role_permissions(
    role_id: str,
    body: AddPermissionsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:update")),
    db: AsyncSession = Depends(get_db),
):
    """Add permissions to a role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    added = []
    for perm_id in body.permission_ids:
        existing = await db.execute(
            select(RolePermission).where(
                and_(RolePermission.role_id == role_id, RolePermission.permission_id == perm_id)
            )
        )
        if not existing.scalar_one_or_none():
            db.add(RolePermission(role_id=role_id, permission_id=perm_id))
            added.append(perm_id)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_permissions_added", "role", role_id, {"permission_ids": added}
    )
    return {"message": f"{len(added)} permissions added"}


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role_permission(
    role_id: str,
    permission_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:update")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a permission from a role."""
    result = await db.execute(
        select(RolePermission).where(
            and_(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        )
    )
    rp = result.scalar_one_or_none()
    if not rp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not assigned to role")

    await db.delete(rp)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_permission_removed", "role", role_id, {"permission_id": permission_id}
    )


@router.get("/roles/{role_id}/members")
async def list_role_members(
    role_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """List users with this role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    count_q = await db.execute(
        select(func.count(UserRole.user_id)).where(UserRole.role_id == role_id)
    )
    total = count_q.scalar()

    member_result = await db.execute(
        select(User, UserRole)
        .join(UserRole, User.id == UserRole.user_id)
        .where(and_(UserRole.role_id == role_id, User.deleted_at.is_(None)))
        .order_by(User.last_name, User.first_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = member_result.all()

    return {
        "items": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "department": u.department,
                "status": u.status,
                "assigned_at": ur.assigned_at.isoformat() if ur.assigned_at else None,
                "assigned_by": str(ur.assigned_by) if ur.assigned_by else None,
                "expires_at": ur.expires_at.isoformat() if ur.expires_at else None,
            }
            for u, ur in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/roles/{role_id}/members")
async def assign_role_to_users(
    role_id: str,
    body: AssignRoleRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:assign")),
    db: AsyncSession = Depends(get_db),
):
    """Assign role to multiple users."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    assigned = []
    skipped = []
    for user_id in body.user_ids:
        existing = await db.execute(
            select(UserRole).where(and_(UserRole.role_id == role_id, UserRole.user_id == user_id))
        )
        if existing.scalar_one_or_none():
            skipped.append(user_id)
            continue
        db.add(UserRole(
            role_id=role_id,
            user_id=user_id,
            assigned_by=current_user.id,
            assigned_at=datetime.now(timezone.utc),
            expires_at=body.expires_at,
        ))
        assigned.append(user_id)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_assigned", "role", role_id,
        {"assigned_to": assigned, "justification": body.justification}
    )
    return {"assigned": len(assigned), "skipped": len(skipped), "user_ids": assigned}


@router.delete("/roles/{role_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role_from_user(
    role_id: str,
    user_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:assign")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a role from a user."""
    result = await db.execute(
        select(UserRole).where(and_(UserRole.role_id == role_id, UserRole.user_id == user_id))
    )
    ur = result.scalar_one_or_none()
    if not ur:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not assigned to user")

    await db.delete(ur)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_removed", "role", role_id, {"user_id": user_id}
    )


@router.get("/roles/{role_id}/sod-conflicts")
async def get_role_sod_conflicts(
    role_id: str,
    current_user: User = Depends(require_permission("sod:read")),
    db: AsyncSession = Depends(get_db),
):
    """Check SoD conflicts for a role."""
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == current_user.tenant_id))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    conflict_result = await db.execute(
        select(SoDConflict).where(
            or_(SoDConflict.role_a_id == role_id, SoDConflict.role_b_id == role_id)
        ).options(selectinload(SoDConflict.policy))
    )
    conflicts = conflict_result.scalars().all()

    return {
        "role_id": role_id,
        "conflicts": [
            {
                "id": str(c.id),
                "policy_id": str(c.policy_id) if c.policy_id else None,
                "policy_name": c.policy.name if c.policy else None,
                "conflicting_role_id": str(c.role_b_id) if str(c.role_a_id) == role_id else str(c.role_a_id),
                "risk_level": c.risk_level,
            }
            for c in conflicts
        ],
    }


@router.post("/roles/mining")
async def trigger_role_mining(
    body: RoleMiningRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger role mining analysis."""
    # Enqueue background job
    job_id = str(__import__("uuid").uuid4())
    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "role_mining_triggered", "role_mining", job_id,
        {"department": body.department, "min_users": body.min_users, "threshold": body.similarity_threshold}
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Role mining analysis has been queued",
    }


@router.get("/roles/recommendations/{user_id}")
async def get_role_recommendations(
    user_id: str,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get role recommendations for a user based on peers."""
    result = await db.execute(
        select(User).where(
            and_(User.id == user_id, User.tenant_id == current_user.tenant_id, User.deleted_at.is_(None))
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Find peers (same department and job title)
    if not user.department:
        return {"user_id": user_id, "recommendations": []}

    peer_result = await db.execute(
        select(User.id)
        .where(
            and_(
                User.department == user.department,
                User.job_title == user.job_title,
                User.id != user.id,
                User.tenant_id == current_user.tenant_id,
                User.deleted_at.is_(None),
                User.status == "active",
            )
        )
        .limit(50)
    )
    peer_ids = [row[0] for row in peer_result.all()]

    if not peer_ids:
        return {"user_id": user_id, "recommendations": []}

    # Get user's current roles
    user_roles_result = await db.execute(
        select(UserRole.role_id).where(UserRole.user_id == user_id)
    )
    user_role_ids = {row[0] for row in user_roles_result.all()}

    # Find roles peers have that user doesn't
    peer_roles_result = await db.execute(
        select(UserRole.role_id, func.count(UserRole.user_id).label("peer_count"))
        .where(and_(UserRole.user_id.in_(peer_ids), UserRole.role_id.notin_(user_role_ids)))
        .group_by(UserRole.role_id)
        .having(func.count(UserRole.user_id) >= max(2, len(peer_ids) // 4))
        .order_by(func.count(UserRole.user_id).desc())
        .limit(10)
    )
    recommended = peer_roles_result.all()

    recommendations = []
    for role_id, peer_count in recommended:
        role_q = await db.execute(select(Role).where(Role.id == role_id))
        role = role_q.scalar_one_or_none()
        if role:
            recommendations.append({
                "role_id": str(role_id),
                "role_name": role.name,
                "peer_count": peer_count,
                "peer_total": len(peer_ids),
                "confidence": round(peer_count / len(peer_ids), 2),
            })

    return {"user_id": user_id, "recommendations": recommendations}


# ---------------------------------------------------------------------------
# Permission Endpoints
# ---------------------------------------------------------------------------

@router.get("/permissions")
async def list_permissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    resource: Optional[str] = None,
    application_id: Optional[str] = None,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all permissions."""
    query = select(Permission)
    count_query = select(func.count(Permission.id))

    if search:
        filt = or_(Permission.name.ilike(f"%{search}%"), Permission.description.ilike(f"%{search}%"))
        query = query.where(filt)
        count_query = count_query.where(filt)
    if resource:
        query = query.where(Permission.resource == resource)
        count_query = count_query.where(Permission.resource == resource)
    if application_id:
        query = query.where(Permission.application_id == application_id)
        count_query = count_query.where(Permission.application_id == application_id)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(Permission.resource, Permission.action)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    permissions = result.scalars().all()

    return {
        "items": [_permission_to_dict(p) for p in permissions],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/permissions", status_code=status.HTTP_201_CREATED)
async def create_permission(
    body: PermissionCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new permission."""
    existing = await db.execute(
        select(Permission).where(
            and_(Permission.resource == body.resource, Permission.action == body.action)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Permission {body.resource}:{body.action} already exists",
        )

    perm = Permission(
        name=body.name,
        description=body.description,
        resource=body.resource,
        action=body.action,
        application_id=body.application_id,
        risk_level=body.risk_level,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "permission_created", "permission", str(perm.id), {"name": perm.name}
    )
    return _permission_to_dict(perm)


@router.get("/permissions/{permission_id}")
async def get_permission(
    permission_id: str,
    current_user: User = Depends(require_permission("roles:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get a permission."""
    result = await db.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return _permission_to_dict(perm)


@router.put("/permissions/{permission_id}")
async def update_permission(
    permission_id: str,
    body: PermissionUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update a permission."""
    result = await db.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    update_data = body.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(perm, key, value)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "permission_updated", "permission", permission_id, {"changes": update_data}
    )
    return _permission_to_dict(perm)


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(
    permission_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("roles:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a permission."""
    result = await db.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    # Check if permission is assigned to any roles
    rp_count = await db.execute(
        select(func.count(RolePermission.role_id)).where(RolePermission.permission_id == permission_id)
    )
    if rp_count.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete permission assigned to roles. Remove from roles first.",
        )

    await db.delete(perm)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "permission_deleted", "permission", permission_id, {"name": perm.name}
    )
