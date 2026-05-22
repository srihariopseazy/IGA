from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.models.access_request import AccessRequest, Approval
from backend.models.user import User

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("/pending-approvals")
async def get_pending_approvals(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get pending approvals for the current user."""
    tenant_id = current_user.tenant_id

    # Get access requests pending approval in this tenant
    query = select(AccessRequest).where(
        and_(
            AccessRequest.tenant_id == tenant_id,
            AccessRequest.status == "pending",
            AccessRequest.deleted_at.is_(None),
        )
    ).order_by(AccessRequest.created_at.desc())

    count_query = select(func.count(AccessRequest.id)).where(
        and_(
            AccessRequest.tenant_id == tenant_id,
            AccessRequest.status == "pending",
            AccessRequest.deleted_at.is_(None),
        )
    )

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    requests = result.scalars().all()

    return {
        "items": [
            {
                "id": str(r.id),
                "request_number": r.request_number,
                "requester_id": str(r.requester_id),
                "target_user_id": str(r.target_user_id),
                "request_type": r.request_type,
                "status": r.status,
                "priority": r.priority,
                "business_justification": r.business_justification,
                "risk_score": r.risk_score,
                "sla_deadline": r.sla_deadline.isoformat() if r.sla_deadline else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in requests
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
