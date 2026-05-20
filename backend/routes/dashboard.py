"""
Dashboard routes — aggregate stats for the IGA platform home page.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.models.user import User
from backend.models.access_request import AccessRequest
from backend.models.sod import SODViolation

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return high-level counts for the dashboard."""
    tenant_id = current_user.tenant_id

    # Total active users in this tenant
    total_users_result = await db.execute(
        select(func.count(User.id)).where(
            and_(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        )
    )
    total_users = total_users_result.scalar() or 0

    # Pending access requests
    try:
        pending_result = await db.execute(
            select(func.count(AccessRequest.id)).where(
                and_(
                    AccessRequest.tenant_id == tenant_id,
                    AccessRequest.status == "pending",
                )
            )
        )
        pending_approvals = pending_result.scalar() or 0
    except Exception:
        pending_approvals = 0

    # Open SoD violations
    try:
        sod_result = await db.execute(
            select(func.count(SODViolation.id)).where(
                and_(
                    SODViolation.tenant_id == tenant_id,
                    SODViolation.status == "open",
                )
            )
        )
        sod_violations = sod_result.scalar() or 0
    except Exception:
        sod_violations = 0

    # High-risk users (from risk_scores if available)
    high_risk_users = 0
    try:
        from backend.models.risk import RiskScore
        risk_result = await db.execute(
            select(func.count(RiskScore.id)).where(
                and_(
                    RiskScore.tenant_id == tenant_id,
                    RiskScore.risk_level.in_(["high", "critical"]),
                )
            )
        )
        high_risk_users = risk_result.scalar() or 0
    except Exception:
        pass

    return {
        "total_users": total_users,
        "pending_approvals": pending_approvals,
        "sod_violations": sod_violations,
        "high_risk_users": high_risk_users,
    }
