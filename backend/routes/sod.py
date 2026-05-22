from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone

from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.models.sod import SODPolicy, SODRule, SODViolation
from backend.models.rbac import Role
from backend.models.user import User
from backend.audit.audit_logger import audit_logger
from pydantic import BaseModel

router = APIRouter(prefix="/sod", tags=["Segregation of Duties"])


class SODPolicyCreate(BaseModel):
    name: str
    description: str = ""
    risk_level: str = "high"


class SODRuleCreate(BaseModel):
    policy_id: UUID
    name: str
    role_id_1: UUID
    role_id_2: UUID
    conflict_type: str = "mutually_exclusive"
    description: str = ""


class MitigationUpdate(BaseModel):
    mitigation_notes: str
    status: str  # mitigated, accepted, resolved


class ConflictSimulation(BaseModel):
    user_id: UUID
    new_role_id: UUID


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


@router.get("/policies")
async def list_sod_policies(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    policy_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    query = select(SODPolicy).where(
        and_(SODPolicy.tenant_id == tenant_id, SODPolicy.deleted_at.is_(None))
    )
    if policy_status:
        query = query.where(SODPolicy.status == policy_status)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(SODPolicy.created_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    policies = result.scalars().all()
    return {"items": [p.to_dict() for p in policies], "total": total, "page": page, "per_page": per_page}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_sod_policy(
    data: SODPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    policy = SODPolicy(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        status="active",
        risk_level=data.risk_level,
        created_by=current_user.id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    await audit_logger.log(
        db,
        str(tenant_id),
        str(current_user.id),
        "sod_policy.create",
        "sod_policies",
        str(policy.id),
        {"name": data.name},
        ip_address=request.client.host if request.client else None,
    )
    return policy.to_dict()


@router.get("/policies/{policy_id}")
async def get_sod_policy(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SODPolicy).where(
            and_(
                SODPolicy.id == policy_id,
                SODPolicy.tenant_id == current_user.tenant_id,
                SODPolicy.deleted_at.is_(None),
            )
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    rules_result = await db.execute(
        select(SODRule).where(
            and_(SODRule.tenant_id == policy_id, SODRule.deleted_at.is_(None))
        )
    )
    rules = rules_result.scalars().all()
    d = policy.to_dict()
    d["rules"] = [r.to_dict() for r in rules]
    return d


@router.put("/policies/{policy_id}")
async def update_sod_policy(
    policy_id: UUID,
    data: SODPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SODPolicy).where(
            and_(SODPolicy.id == policy_id, SODPolicy.tenant_id == current_user.tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Not found")
    policy.name = data.name
    policy.description = data.description
    policy.risk_level = data.risk_level
    await db.commit()
    return policy.to_dict()


@router.get("/rules")
async def list_sod_rules(
    policy_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(SODRule).where(
        and_(SODRule.tenant_id == current_user.tenant_id, SODRule.deleted_at.is_(None))
    )
    if policy_id:
        query = query.where(SODRule.tenant_id == policy_id)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return {
        "items": [r.to_dict() for r in result.scalars().all()],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_sod_rule(
    data: SODRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = SODRule(
        tenant_id=current_user.tenant_id,
        policy_id=data.policy_id,
        name=data.name,
        role_id_1=data.role_id_1,
        role_id_2=data.role_id_2,
        conflict_type=data.conflict_type,
        description=data.description,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule.to_dict()


@router.delete("/rules/{rule_id}")
async def delete_sod_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SODRule).where(
            and_(SODRule.id == rule_id, SODRule.tenant_id == current_user.tenant_id)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Not found")
    rule.soft_delete()
    await db.commit()
    return {"success": True}


@router.get("/violations")
async def list_sod_violations(
    user_id: Optional[UUID] = Query(None),
    violation_status: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(SODViolation).where(SODViolation.tenant_id == current_user.tenant_id)
    if user_id:
        query = query.where(SODViolation.user_id == user_id)
    if violation_status:
        query = query.where(SODViolation.status == violation_status)
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(SODViolation.detected_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return {
        "items": [v.to_dict() for v in result.scalars().all()],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/violations/{violation_id}")
async def get_violation(
    violation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SODViolation).where(
            and_(
                SODViolation.id == violation_id,
                SODViolation.tenant_id == current_user.tenant_id,
            )
        )
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    return v.to_dict()


@router.post("/violations/{violation_id}/mitigate")
async def mitigate_violation(
    violation_id: UUID,
    data: MitigationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SODViolation).where(
            and_(
                SODViolation.id == violation_id,
                SODViolation.tenant_id == current_user.tenant_id,
            )
        )
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    v.mitigation_notes = data.mitigation_notes
    v.status = data.status
    v.mitigated_by = current_user.id
    v.mitigated_at = datetime.now(timezone.utc)
    await db.commit()
    await audit_logger.log(
        db,
        str(current_user.tenant_id),
        str(current_user.id),
        "sod_violation.mitigate",
        "sod_violations",
        str(violation_id),
        {"status": data.status},
        ip_address=request.client.host if request.client else None,
    )
    return v.to_dict()


@router.post("/simulate")
async def simulate_sod_conflict(
    data: ConflictSimulation,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from backend.models.rbac import UserRole

    roles_result = await db.execute(
        select(UserRole.role_id).where(
            and_(
                UserRole.user_id == data.user_id,
                UserRole.tenant_id == current_user.tenant_id,
                UserRole.deleted_at.is_(None),
            )
        )
    )
    current_role_ids = [str(r[0]) for r in roles_result.all()]
    new_role_id_str = str(data.new_role_id)

    rules_result = await db.execute(
        select(SODRule).where(
            and_(
                SODRule.tenant_id == current_user.tenant_id,
                SODRule.deleted_at.is_(None),
            )
        )
    )
    rules = rules_result.scalars().all()

    conflicts = []
    for rule in rules:
        r1 = str(rule.role_id_1)
        r2 = str(rule.role_id_2)
        if (r1 == new_role_id_str and r2 in current_role_ids) or (
            r2 == new_role_id_str and r1 in current_role_ids
        ):
            conflicts.append(
                {
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "conflict_type": rule.conflict_type,
                    "description": rule.description,
                }
            )

    return {
        "user_id": str(data.user_id),
        "new_role_id": str(data.new_role_id),
        "would_violate": len(conflicts) > 0,
        "conflicts": conflicts,
    }


@router.get("/stats")
async def get_sod_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id
    total = await db.execute(
        select(func.count(SODViolation.id)).where(SODViolation.tenant_id == tenant_id)
    )
    open_count = await db.execute(
        select(func.count(SODViolation.id)).where(
            and_(SODViolation.tenant_id == tenant_id, SODViolation.status == "open")
        )
    )
    critical = await db.execute(
        select(func.count(SODViolation.id)).where(
            and_(
                SODViolation.tenant_id == tenant_id,
                SODViolation.risk_score >= 80,
                SODViolation.status == "open",
            )
        )
    )
    policies_count = await db.execute(
        select(func.count(SODPolicy.id)).where(
            and_(SODPolicy.tenant_id == tenant_id, SODPolicy.deleted_at.is_(None))
        )
    )
    rules_count = await db.execute(
        select(func.count(SODRule.id)).where(
            and_(SODRule.tenant_id == tenant_id, SODRule.deleted_at.is_(None))
        )
    )
    return {
        "total_violations": total.scalar(),
        "open_violations": open_count.scalar(),
        "critical_violations": critical.scalar(),
        "policies_count": policies_count.scalar(),
        "rules_count": rules_count.scalar(),
    }
