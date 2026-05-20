"""
Access request routes for the IGA platform.
Handles request submission, approval workflows, catalog browsing, and bulk operations.
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
from backend.utils.notifications import notify_user
from backend.models.user import User
from backend.models.access_request import AccessRequest, AccessRequestItem, Approval as ApprovalStep
from backend.models.rbac import Role
from backend.models.application import Entitlement
from backend.models.workflow import WorkflowInstance

router = APIRouter(prefix="/access-requests", tags=["Access Requests"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AccessRequestItemSchema(BaseModel):
    resource_type: str = Field(..., pattern="^(role|entitlement|group|application)$")
    resource_id: str
    access_level: Optional[str] = None

class SubmitAccessRequest(BaseModel):
    items: List[AccessRequestItemSchema] = Field(..., min_items=1)
    justification: str = Field(..., min_length=10, max_length=2000)
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")
    requested_for_id: Optional[str] = None  # If requesting on behalf of someone
    duration_days: Optional[int] = Field(None, ge=1, le=365)

class ApproveRequest(BaseModel):
    comment: Optional[str] = None

class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)

class DelegateRequest(BaseModel):
    delegate_to_user_id: str
    reason: Optional[str] = None

class BulkApproveRequest(BaseModel):
    request_ids: List[str] = Field(..., min_items=1)
    comment: Optional[str] = None

class BulkRejectRequest(BaseModel):
    request_ids: List[str] = Field(..., min_items=1)
    reason: str = Field(..., min_length=5)

class EmergencyAccessRequest(BaseModel):
    resource_type: str
    resource_id: str
    justification: str = Field(..., min_length=20)
    duration_hours: int = Field(8, ge=1, le=72)
    incident_ticket: Optional[str] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_to_dict(req: AccessRequest) -> dict:
    return {
        "id": str(req.id),
        "requester_id": str(req.requester_id),
        "requested_for_id": str(req.requested_for_id) if req.requested_for_id else None,
        "status": req.status,
        "priority": req.priority,
        "justification": req.justification,
        "resource_type": req.resource_type,
        "resource_id": str(req.resource_id) if req.resource_id else None,
        "duration_days": req.duration_days,
        "created_at": req.created_at.isoformat(),
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        "rejection_reason": req.rejection_reason,
        "is_emergency": req.is_emergency,
        "tenant_id": str(req.tenant_id),
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_access_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    requester_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(require_permission("access_requests:read")),
    db: AsyncSession = Depends(get_db),
):
    """List all access requests with filtering."""
    query = select(AccessRequest).where(AccessRequest.tenant_id == current_user.tenant_id)
    count_query = select(func.count(AccessRequest.id)).where(AccessRequest.tenant_id == current_user.tenant_id)

    if status_filter:
        query = query.where(AccessRequest.status == status_filter)
        count_query = count_query.where(AccessRequest.status == status_filter)
    if requester_id:
        query = query.where(AccessRequest.requester_id == requester_id)
        count_query = count_query.where(AccessRequest.requester_id == requester_id)
    if resource_type:
        query = query.where(AccessRequest.resource_type == resource_type)
        count_query = count_query.where(AccessRequest.resource_type == resource_type)
    if priority:
        query = query.where(AccessRequest.priority == priority)
        count_query = count_query.where(AccessRequest.priority == priority)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(AccessRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    requests = result.scalars().all()

    return {
        "items": [_request_to_dict(r) for r in requests],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_access_request(
    body: SubmitAccessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a new access request."""
    # Determine the target user
    target_user_id = body.requested_for_id or str(current_user.id)

    # Validate each requested resource exists
    for item in body.items:
        if item.resource_type == "role":
            r = await db.execute(
                select(Role).where(and_(
                    Role.id == item.resource_id,
                    Role.tenant_id == current_user.tenant_id,
                    Role.is_requestable == True,
                ))
            )
            if not r.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Role {item.resource_id} not found or not requestable",
                )
        elif item.resource_type == "entitlement":
            e = await db.execute(
                select(Entitlement).where(Entitlement.id == item.resource_id)
            )
            if not e.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Entitlement {item.resource_id} not found",
                )

    # Create one request per item (or group under one parent request)
    created_requests = []
    for item in body.items:
        req = AccessRequest(
            requester_id=current_user.id,
            requested_for_id=target_user_id if target_user_id != str(current_user.id) else None,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            access_level=item.access_level,
            justification=body.justification,
            priority=body.priority,
            duration_days=body.duration_days,
            status="pending",
            tenant_id=current_user.tenant_id,
        )
        db.add(req)
        await db.flush()
        created_requests.append(req)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "access_request_submitted", "access_request",
        str(created_requests[0].id) if created_requests else None,
        {"item_count": len(created_requests), "priority": body.priority}
    )

    return {
        "message": "Access request submitted successfully",
        "requests": [_request_to_dict(r) for r in created_requests],
    }


@router.get("/catalog")
async def browse_access_catalog(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = None,
    resource_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Browse the access catalog (requestable roles and entitlements)."""
    results = []

    if resource_type in (None, "role"):
        role_query = select(Role).where(
            and_(
                Role.tenant_id == current_user.tenant_id,
                Role.is_requestable == True,
            )
        )
        if search:
            role_query = role_query.where(
                or_(Role.name.ilike(f"%{search}%"), Role.description.ilike(f"%{search}%"))
            )
        role_result = await db.execute(role_query.order_by(Role.name).limit(page_size))
        roles = role_result.scalars().all()
        for r in roles:
            results.append({
                "id": str(r.id),
                "type": "role",
                "name": r.name,
                "description": r.description,
                "risk_level": r.risk_level,
                "requires_approval": r.requires_approval,
            })

    if resource_type in (None, "entitlement"):
        ent_query = select(Entitlement).where(Entitlement.is_requestable == True)
        if search:
            ent_query = ent_query.where(
                or_(Entitlement.name.ilike(f"%{search}%"), Entitlement.description.ilike(f"%{search}%"))
            )
        ent_result = await db.execute(ent_query.order_by(Entitlement.name).limit(page_size))
        entitlements = ent_result.scalars().all()
        for e in entitlements:
            results.append({
                "id": str(e.id),
                "type": "entitlement",
                "name": e.name,
                "description": e.description,
                "application_id": str(e.application_id) if e.application_id else None,
            })

    return {"items": results, "total": len(results)}


@router.get("/my-requests")
async def my_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's access requests."""
    query = select(AccessRequest).where(AccessRequest.requester_id == current_user.id)
    count_query = select(func.count(AccessRequest.id)).where(AccessRequest.requester_id == current_user.id)

    if status_filter:
        query = query.where(AccessRequest.status == status_filter)
        count_query = count_query.where(AccessRequest.status == status_filter)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(AccessRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    requests = result.scalars().all()

    return {
        "items": [_request_to_dict(r) for r in requests],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/my-approvals")
async def my_approvals(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List access requests pending current user's approval."""
    query = (
        select(AccessRequest)
        .join(ApprovalStep, AccessRequest.id == ApprovalStep.request_id)
        .where(
            and_(
                ApprovalStep.approver_id == current_user.id,
                ApprovalStep.status == "pending",
                AccessRequest.status == "pending",
            )
        )
    )
    count_query = (
        select(func.count(AccessRequest.id))
        .join(ApprovalStep, AccessRequest.id == ApprovalStep.request_id)
        .where(
            and_(
                ApprovalStep.approver_id == current_user.id,
                ApprovalStep.status == "pending",
                AccessRequest.status == "pending",
            )
        )
    )

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(AccessRequest.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    requests = result.scalars().all()

    return {
        "items": [_request_to_dict(r) for r in requests],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{request_id}")
async def get_access_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get access request details with approval timeline."""
    result = await db.execute(
        select(AccessRequest)
        .where(
            and_(
                AccessRequest.id == request_id,
                AccessRequest.tenant_id == current_user.tenant_id,
            )
        )
        .options(selectinload(AccessRequest.approval_steps))
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found")

    # Only requester, target user, or admins can view
    if str(req.requester_id) != str(current_user.id):
        # Check if user is an approver
        is_approver = any(
            str(step.approver_id) == str(current_user.id) for step in req.approval_steps
        )
        if not is_approver:
            require_permission("access_requests:read")(current_user)

    data = _request_to_dict(req)
    data["approval_timeline"] = [
        {
            "step_id": str(s.id),
            "step_order": s.step_order,
            "approver_id": str(s.approver_id) if s.approver_id else None,
            "approver_type": s.approver_type,
            "status": s.status,
            "comment": s.comment,
            "decided_at": s.decided_at.isoformat() if s.decided_at else None,
        }
        for s in sorted(req.approval_steps, key=lambda x: x.step_order)
    ]
    return data


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_access_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an access request (only by requester, only if pending)."""
    result = await db.execute(
        select(AccessRequest).where(
            and_(
                AccessRequest.id == request_id,
                AccessRequest.requester_id == current_user.id,
            )
        )
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found")

    if req.status not in ("pending", "in_review"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel request with status '{req.status}'",
        )

    req.status = "cancelled"
    req.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "access_request_cancelled", "access_request", request_id, {}
    )


@router.post("/{request_id}/approve")
async def approve_request(
    request_id: str,
    body: ApproveRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve an access request."""
    result = await db.execute(
        select(AccessRequest)
        .where(
            and_(
                AccessRequest.id == request_id,
                AccessRequest.tenant_id == current_user.tenant_id,
                AccessRequest.status == "pending",
            )
        )
        .options(selectinload(AccessRequest.approval_steps))
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found or not pending")

    # Find pending step for this approver
    pending_step = next(
        (s for s in req.approval_steps
         if str(s.approver_id) == str(current_user.id) and s.status == "pending"),
        None,
    )
    if not pending_step:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to approve this request")

    pending_step.status = "approved"
    pending_step.comment = body.comment
    pending_step.decided_at = datetime.now(timezone.utc)

    # Check if all steps approved
    all_approved = all(
        s.status == "approved" for s in req.approval_steps
    )
    if all_approved:
        req.status = "approved"
        req.resolved_at = datetime.now(timezone.utc)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "access_request_approved", "access_request", request_id,
        {"approver": str(current_user.id), "comment": body.comment, "fully_approved": all_approved}
    )
    background_tasks.add_task(
        notify_user, str(req.requester_id),
        "Access Request Approved" if all_approved else "Access Request Step Approved",
        f"Your access request has been {'fully approved' if all_approved else 'approved at one step'}.",
    )

    return {"message": "Request approved", "fully_approved": all_approved, "status": req.status}


@router.post("/{request_id}/reject")
async def reject_request(
    request_id: str,
    body: RejectRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject an access request."""
    result = await db.execute(
        select(AccessRequest)
        .where(
            and_(
                AccessRequest.id == request_id,
                AccessRequest.tenant_id == current_user.tenant_id,
                AccessRequest.status == "pending",
            )
        )
        .options(selectinload(AccessRequest.approval_steps))
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found or not pending")

    pending_step = next(
        (s for s in req.approval_steps
         if str(s.approver_id) == str(current_user.id) and s.status == "pending"),
        None,
    )
    if not pending_step:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to reject this request")

    pending_step.status = "rejected"
    pending_step.comment = body.reason
    pending_step.decided_at = datetime.now(timezone.utc)

    req.status = "rejected"
    req.rejection_reason = body.reason
    req.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "access_request_rejected", "access_request", request_id, {"reason": body.reason}
    )
    background_tasks.add_task(
        notify_user, str(req.requester_id),
        "Access Request Rejected",
        f"Your access request was rejected: {body.reason}",
    )

    return {"message": "Request rejected", "status": req.status}


@router.post("/{request_id}/delegate")
async def delegate_approval(
    request_id: str,
    body: DelegateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delegate an approval step to another user."""
    result = await db.execute(
        select(AccessRequest)
        .where(
            and_(
                AccessRequest.id == request_id,
                AccessRequest.tenant_id == current_user.tenant_id,
            )
        )
        .options(selectinload(AccessRequest.approval_steps))
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found")

    pending_step = next(
        (s for s in req.approval_steps
         if str(s.approver_id) == str(current_user.id) and s.status == "pending"),
        None,
    )
    if not pending_step:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No pending approval step found for you")

    # Validate delegate user exists
    delegate_result = await db.execute(
        select(User).where(
            and_(
                User.id == body.delegate_to_user_id,
                User.tenant_id == current_user.tenant_id,
                User.status == "active",
            )
        )
    )
    delegate = delegate_result.scalar_one_or_none()
    if not delegate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegate user not found")

    original_approver_id = pending_step.approver_id
    pending_step.approver_id = body.delegate_to_user_id
    pending_step.delegated_from_id = original_approver_id
    pending_step.delegation_reason = body.reason
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "access_request_delegated", "access_request", request_id,
        {"delegated_to": body.delegate_to_user_id, "reason": body.reason}
    )
    return {"message": "Approval delegated", "delegated_to": body.delegate_to_user_id}


@router.post("/bulk-approve")
async def bulk_approve(
    body: BulkApproveRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk approve multiple access requests."""
    approved = []
    failed = []
    for request_id in body.request_ids:
        result = await db.execute(
            select(AccessRequest)
            .where(
                and_(
                    AccessRequest.id == request_id,
                    AccessRequest.tenant_id == current_user.tenant_id,
                    AccessRequest.status == "pending",
                )
            )
            .options(selectinload(AccessRequest.approval_steps))
        )
        req = result.scalar_one_or_none()
        if not req:
            failed.append({"id": request_id, "reason": "Not found or not pending"})
            continue

        step = next(
            (s for s in req.approval_steps
             if str(s.approver_id) == str(current_user.id) and s.status == "pending"),
            None,
        )
        if not step:
            failed.append({"id": request_id, "reason": "No pending step for this approver"})
            continue

        step.status = "approved"
        step.comment = body.comment
        step.decided_at = datetime.now(timezone.utc)

        all_approved = all(s.status == "approved" for s in req.approval_steps)
        if all_approved:
            req.status = "approved"
            req.resolved_at = datetime.now(timezone.utc)

        approved.append(request_id)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "bulk_access_requests_approved", "access_request", None,
        {"approved": approved, "failed_count": len(failed)}
    )
    return {"approved": len(approved), "failed": len(failed), "failed_details": failed}


@router.post("/bulk-reject")
async def bulk_reject(
    body: BulkRejectRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk reject multiple access requests."""
    rejected = []
    failed = []
    for request_id in body.request_ids:
        result = await db.execute(
            select(AccessRequest)
            .where(
                and_(
                    AccessRequest.id == request_id,
                    AccessRequest.tenant_id == current_user.tenant_id,
                    AccessRequest.status == "pending",
                )
            )
            .options(selectinload(AccessRequest.approval_steps))
        )
        req = result.scalar_one_or_none()
        if not req:
            failed.append({"id": request_id, "reason": "Not found or not pending"})
            continue

        step = next(
            (s for s in req.approval_steps
             if str(s.approver_id) == str(current_user.id) and s.status == "pending"),
            None,
        )
        if not step:
            failed.append({"id": request_id, "reason": "No pending step for this approver"})
            continue

        step.status = "rejected"
        step.comment = body.reason
        step.decided_at = datetime.now(timezone.utc)
        req.status = "rejected"
        req.rejection_reason = body.reason
        req.resolved_at = datetime.now(timezone.utc)
        rejected.append(request_id)

    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "bulk_access_requests_rejected", "access_request", None,
        {"rejected": rejected, "reason": body.reason}
    )
    return {"rejected": len(rejected), "failed": len(failed), "failed_details": failed}


@router.get("/stats")
async def access_request_stats(
    current_user: User = Depends(require_permission("access_requests:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get access request dashboard statistics."""
    from sqlalchemy import case

    stats_result = await db.execute(
        select(
            func.count(AccessRequest.id).label("total"),
            func.sum(case((AccessRequest.status == "pending", 1), else_=0)).label("pending"),
            func.sum(case((AccessRequest.status == "approved", 1), else_=0)).label("approved"),
            func.sum(case((AccessRequest.status == "rejected", 1), else_=0)).label("rejected"),
            func.sum(case((AccessRequest.status == "cancelled", 1), else_=0)).label("cancelled"),
            func.sum(case((AccessRequest.is_emergency == True, 1), else_=0)).label("emergency"),
        ).where(AccessRequest.tenant_id == current_user.tenant_id)
    )
    row = stats_result.one()

    # My pending approvals
    my_pending = await db.execute(
        select(func.count(ApprovalStep.id)).where(
            and_(
                ApprovalStep.approver_id == current_user.id,
                ApprovalStep.status == "pending",
            )
        )
    )

    return {
        "total": row.total or 0,
        "pending": row.pending or 0,
        "approved": row.approved or 0,
        "rejected": row.rejected or 0,
        "cancelled": row.cancelled or 0,
        "emergency": row.emergency or 0,
        "my_pending_approvals": my_pending.scalar() or 0,
    }


@router.post("/emergency", status_code=status.HTTP_201_CREATED)
async def submit_emergency_access(
    body: EmergencyAccessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit an emergency access request with expedited review."""
    req = AccessRequest(
        requester_id=current_user.id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        justification=body.justification,
        priority="urgent",
        duration_days=(body.duration_hours + 23) // 24,
        status="pending",
        tenant_id=current_user.tenant_id,
        is_emergency=True,
        emergency_ticket=body.incident_ticket,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "emergency_access_requested", "access_request", str(req.id),
        {
            "resource_type": body.resource_type,
            "resource_id": body.resource_id,
            "duration_hours": body.duration_hours,
            "incident_ticket": body.incident_ticket,
        }
    )

    return {
        "message": "Emergency access request submitted. Approvers have been notified.",
        "request": _request_to_dict(req),
    }
