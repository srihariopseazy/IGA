"""
Certification / access review routes for the IGA platform.
Handles campaign management, reviewer workflows, and bulk operations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_, case
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import io
import csv

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_permission
from backend.utils.audit import log_action
from backend.utils.notifications import notify_user
from backend.models.user import User
from backend.models.certification import (
    CertificationCampaign, CertificationItem,
)

router = APIRouter(prefix="/certifications", tags=["Certifications"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    campaign_type: str = Field("user_access", pattern="^(user_access|role_entitlement|application|privileged)$")
    scope_filter: Optional[dict] = None
    reviewer_type: str = Field("manager", pattern="^(manager|owner|role|specific_user)$")
    reviewer_ids: List[str] = []
    due_date: Optional[datetime] = None
    reminder_days_before: int = Field(3, ge=1, le=30)
    certify_by_default: bool = False
    resource_ids: Optional[List[str]] = None

class CertifyItemRequest(BaseModel):
    comment: Optional[str] = None

class RevokeItemRequest(BaseModel):
    reason: str = Field(..., min_length=5)

class DelegateReviewRequest(BaseModel):
    delegate_to_user_id: str
    reason: Optional[str] = None

class BulkCertifyRequest(BaseModel):
    item_ids: List[str] = Field(..., min_items=1)
    comment: Optional[str] = None

class BulkRevokeRequest(BaseModel):
    item_ids: List[str] = Field(..., min_items=1)
    reason: str = Field(..., min_length=5)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign_to_dict(c: CertificationCampaign) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "campaign_type": c.campaign_type,
        "status": c.status,
        "reviewer_type": c.reviewer_type,
        "due_date": c.due_date.isoformat() if c.due_date else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "tenant_id": str(c.tenant_id),
        "created_at": c.created_at.isoformat(),
        "certify_by_default": c.certify_by_default,
    }

def _item_to_dict(item: CertificationItem) -> dict:
    return {
        "id": str(item.id),
        "campaign_id": str(item.campaign_id),
        "user_id": str(item.user_id),
        "resource_type": item.resource_type,
        "resource_id": str(item.resource_id) if item.resource_id else None,
        "reviewer_id": str(item.reviewer_id) if item.reviewer_id else None,
        "status": item.status,
        "decision": item.decision,
        "decision_comment": item.decision_comment,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "delegated_to_id": str(item.delegated_to_id) if item.delegated_to_id else None,
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/campaigns")
async def list_campaigns(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    campaign_type: Optional[str] = None,
    current_user: User = Depends(require_permission("certifications:read")),
    db: AsyncSession = Depends(get_db),
):
    """List certification campaigns."""
    query = select(CertificationCampaign).where(CertificationCampaign.tenant_id == current_user.tenant_id)
    count_q = select(func.count(CertificationCampaign.id)).where(CertificationCampaign.tenant_id == current_user.tenant_id)

    if status_filter:
        query = query.where(CertificationCampaign.status == status_filter)
        count_q = count_q.where(CertificationCampaign.status == status_filter)
    if campaign_type:
        query = query.where(CertificationCampaign.campaign_type == campaign_type)
        count_q = count_q.where(CertificationCampaign.campaign_type == campaign_type)

    total = (await db.execute(count_q)).scalar()
    result = await db.execute(
        query.order_by(CertificationCampaign.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    campaigns = result.scalars().all()

    return {
        "items": [_campaign_to_dict(c) for c in campaigns],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("certifications:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new certification campaign."""
    campaign = CertificationCampaign(
        name=body.name,
        description=body.description,
        campaign_type=body.campaign_type,
        scope_filter=body.scope_filter,
        reviewer_type=body.reviewer_type,
        reviewer_ids=body.reviewer_ids,
        due_date=body.due_date,
        reminder_days_before=body.reminder_days_before,
        certify_by_default=body.certify_by_default,
        status="draft",
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_campaign_created", "certification_campaign", str(campaign.id),
        {"name": campaign.name}
    )
    return _campaign_to_dict(campaign)


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    current_user: User = Depends(require_permission("certifications:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get campaign details with progress stats."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    stats = await db.execute(
        select(
            func.count(CertificationItem.id).label("total"),
            func.sum(case((CertificationItem.decision == "certify", 1), else_=0)).label("certified"),
            func.sum(case((CertificationItem.decision == "revoke", 1), else_=0)).label("revoked"),
            func.sum(case((CertificationItem.status == "pending", 1), else_=0)).label("pending"),
        ).where(CertificationItem.campaign_id == campaign_id)
    )
    s = stats.one()

    data = _campaign_to_dict(campaign)
    data["stats"] = {
        "total": s.total or 0,
        "certified": s.certified or 0,
        "revoked": s.revoked or 0,
        "pending": s.pending or 0,
        "completion_rate": round(((s.certified or 0) + (s.revoked or 0)) / max(s.total or 1, 1) * 100, 1),
    }
    return data


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("certifications:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Start a certification campaign. Generates review items."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign is already {campaign.status}",
        )

    campaign.status = "active"
    campaign.started_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_campaign_started", "certification_campaign", campaign_id, {}
    )
    return {"message": "Campaign started", "campaign_id": campaign_id, "status": "active"}


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("certifications:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Pause an active campaign."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign is not active")

    campaign.status = "paused"
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_campaign_paused", "certification_campaign", campaign_id, {}
    )
    return {"message": "Campaign paused", "campaign_id": campaign_id}


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("certifications:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a campaign."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status in ("completed", "cancelled"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Campaign is already {campaign.status}")

    campaign.status = "cancelled"
    campaign.completed_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_campaign_cancelled", "certification_campaign", campaign_id, {}
    )
    return {"message": "Campaign cancelled", "campaign_id": campaign_id}


@router.get("/campaigns/{campaign_id}/items")
async def list_campaign_items(
    campaign_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    reviewer_id: Optional[str] = None,
    current_user: User = Depends(require_permission("certifications:read")),
    db: AsyncSession = Depends(get_db),
):
    """List certification items in a campaign."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    query = select(CertificationItem).where(CertificationItem.campaign_id == campaign_id)
    count_q = select(func.count(CertificationItem.id)).where(CertificationItem.campaign_id == campaign_id)

    if status_filter:
        query = query.where(CertificationItem.status == status_filter)
        count_q = count_q.where(CertificationItem.status == status_filter)
    if reviewer_id:
        query = query.where(CertificationItem.reviewer_id == reviewer_id)
        count_q = count_q.where(CertificationItem.reviewer_id == reviewer_id)

    total = (await db.execute(count_q)).scalar()
    items_result = await db.execute(
        query.order_by(CertificationItem.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = items_result.scalars().all()

    return {
        "items": [_item_to_dict(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/my-reviews")
async def my_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    campaign_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get certification items assigned to the current user for review."""
    query = select(CertificationItem).where(
        and_(
            or_(
                CertificationItem.reviewer_id == current_user.id,
                CertificationItem.delegated_to_id == current_user.id,
            ),
            CertificationItem.status == "pending",
        )
    )
    count_q = select(func.count(CertificationItem.id)).where(
        and_(
            or_(
                CertificationItem.reviewer_id == current_user.id,
                CertificationItem.delegated_to_id == current_user.id,
            ),
            CertificationItem.status == "pending",
        )
    )

    if campaign_id:
        query = query.where(CertificationItem.campaign_id == campaign_id)
        count_q = count_q.where(CertificationItem.campaign_id == campaign_id)

    total = (await db.execute(count_q)).scalar()
    items_result = await db.execute(
        query.order_by(CertificationItem.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = items_result.scalars().all()

    return {
        "items": [_item_to_dict(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/items/{item_id}/certify")
async def certify_item(
    item_id: str,
    body: CertifyItemRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Certify (approve) a certification item."""
    result = await db.execute(select(CertificationItem).where(CertificationItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    effective_reviewer = item.delegated_to_id or item.reviewer_id
    if str(effective_reviewer) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to certify this item")

    if item.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not pending review")

    item.decision = "certify"
    item.decision_comment = body.comment
    item.decided_by = current_user.id
    item.decided_at = datetime.now(timezone.utc)
    item.status = "completed"
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_item_certified", "certification_item", item_id,
        {"campaign_id": str(item.campaign_id)}
    )
    return {"message": "Item certified", "item_id": item_id, "decision": "certify"}


@router.post("/items/{item_id}/revoke")
async def revoke_item(
    item_id: str,
    body: RevokeItemRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke access during certification review."""
    result = await db.execute(select(CertificationItem).where(CertificationItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    effective_reviewer = item.delegated_to_id or item.reviewer_id
    if str(effective_reviewer) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to revoke this item")

    if item.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not pending review")

    item.decision = "revoke"
    item.decision_comment = body.reason
    item.decided_by = current_user.id
    item.decided_at = datetime.now(timezone.utc)
    item.status = "completed"
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_item_revoked", "certification_item", item_id,
        {"campaign_id": str(item.campaign_id), "reason": body.reason}
    )
    return {"message": "Access revoked", "item_id": item_id, "decision": "revoke"}


@router.post("/items/bulk-certify")
async def bulk_certify(
    body: BulkCertifyRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk certify multiple items."""
    certified = []
    failed = []
    for item_id in body.item_ids:
        result = await db.execute(select(CertificationItem).where(CertificationItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item or item.status != "pending":
            failed.append({"id": item_id, "reason": "Not found or not pending"})
            continue
        effective_reviewer = item.delegated_to_id or item.reviewer_id
        if str(effective_reviewer) != str(current_user.id):
            failed.append({"id": item_id, "reason": "Not authorized"})
            continue
        item.decision = "certify"
        item.decision_comment = body.comment
        item.decided_by = current_user.id
        item.decided_at = datetime.now(timezone.utc)
        item.status = "completed"
        certified.append(item_id)

    await db.commit()
    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "bulk_certification_certified", "certification_item", None,
        {"certified": certified, "failed_count": len(failed)}
    )
    return {"certified": len(certified), "failed": len(failed), "failed_details": failed}


@router.post("/items/bulk-revoke")
async def bulk_revoke(
    body: BulkRevokeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk revoke multiple items."""
    revoked = []
    failed = []
    for item_id in body.item_ids:
        result = await db.execute(select(CertificationItem).where(CertificationItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item or item.status != "pending":
            failed.append({"id": item_id, "reason": "Not found or not pending"})
            continue
        effective_reviewer = item.delegated_to_id or item.reviewer_id
        if str(effective_reviewer) != str(current_user.id):
            failed.append({"id": item_id, "reason": "Not authorized"})
            continue
        item.decision = "revoke"
        item.decision_comment = body.reason
        item.decided_by = current_user.id
        item.decided_at = datetime.now(timezone.utc)
        item.status = "completed"
        revoked.append(item_id)

    await db.commit()
    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "bulk_certification_revoked", "certification_item", None,
        {"revoked": revoked, "reason": body.reason}
    )
    return {"revoked": len(revoked), "failed": len(failed), "failed_details": failed}


@router.post("/items/{item_id}/delegate")
async def delegate_review(
    item_id: str,
    body: DelegateReviewRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delegate a review item to another user."""
    result = await db.execute(select(CertificationItem).where(CertificationItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    effective_reviewer = item.delegated_to_id or item.reviewer_id
    if str(effective_reviewer) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delegate this item")

    if item.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not pending")

    delegate_result = await db.execute(
        select(User).where(
            and_(
                User.id == body.delegate_to_user_id,
                User.tenant_id == current_user.tenant_id,
                User.is_active == True,
            )
        )
    )
    if not delegate_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegate user not found")

    item.delegated_to_id = body.delegate_to_user_id
    item.delegation_reason = body.reason
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "certification_item_delegated", "certification_item", item_id,
        {"delegated_to": body.delegate_to_user_id}
    )
    return {"message": "Review delegated", "delegated_to": body.delegate_to_user_id}


@router.get("/campaigns/{campaign_id}/stats")
async def campaign_stats(
    campaign_id: str,
    current_user: User = Depends(require_permission("certifications:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for a certification campaign."""
    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    stats_result = await db.execute(
        select(
            func.count(CertificationItem.id).label("total"),
            func.sum(case((CertificationItem.decision == "certify", 1), else_=0)).label("certified"),
            func.sum(case((CertificationItem.decision == "revoke", 1), else_=0)).label("revoked"),
            func.sum(case((CertificationItem.status == "pending", 1), else_=0)).label("pending"),
        ).where(CertificationItem.campaign_id == campaign_id)
    )
    s = stats_result.one()
    total = s.total or 0
    certified = s.certified or 0
    revoked = s.revoked or 0
    pending = s.pending or 0
    completed = certified + revoked

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.name,
        "status": campaign.status,
        "total_items": total,
        "certified": certified,
        "revoked": revoked,
        "pending": pending,
        "completed": completed,
        "completion_rate": round(completed / max(total, 1) * 100, 1),
        "certify_rate": round(certified / max(completed, 1) * 100, 1),
        "revoke_rate": round(revoked / max(completed, 1) * 100, 1),
        "due_date": campaign.due_date.isoformat() if campaign.due_date else None,
    }


@router.get("/campaigns/{campaign_id}/export")
async def export_campaign(
    campaign_id: str,
    current_user: User = Depends(require_permission("certifications:read")),
    db: AsyncSession = Depends(get_db),
):
    """Export certification campaign results as CSV."""
    from fastapi.responses import StreamingResponse

    result = await db.execute(
        select(CertificationCampaign).where(
            and_(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == current_user.tenant_id,
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    items_result = await db.execute(
        select(CertificationItem).where(CertificationItem.campaign_id == campaign_id)
    )
    items = items_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "item_id", "user_id", "resource_type", "resource_id",
        "reviewer_id", "status", "decision", "decision_comment", "decided_at",
    ])
    for item in items:
        writer.writerow([
            str(item.id), str(item.user_id), item.resource_type,
            str(item.resource_id) if item.resource_id else "",
            str(item.reviewer_id) if item.reviewer_id else "",
            item.status, item.decision or "", item.decision_comment or "",
            item.decided_at.isoformat() if item.decided_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}.csv"},
    )
