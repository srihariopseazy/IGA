from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.risk import (
    AccessRecommendation,
    IdentityRiskHistory,
    RiskScore,
    UserBehaviorEvent,
)
from backend.models.user import User

router = APIRouter(prefix="/risk", tags=["Risk"])


class RecommendationAction(BaseModel):
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


@router.get("/scores")
async def list_risk_scores(
    risk_level: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
    max_score: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(RiskScore).where(RiskScore.tenant_id == current_user.tenant_id)
    if risk_level:
        query = query.where(RiskScore.risk_level == risk_level)
    if min_score is not None:
        query = query.where(RiskScore.overall_score >= min_score)
    if max_score is not None:
        query = query.where(RiskScore.overall_score <= max_score)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(RiskScore.overall_score)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    scores = rows.scalars().all()

    return {
        "items": [s.to_dict() for s in scores],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/scores/{user_id}")
async def get_user_risk_score(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(RiskScore).where(
            and_(
                RiskScore.user_id == user_id,
                RiskScore.tenant_id == current_user.tenant_id,
            )
        )
    )
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="Risk score not found for this user")

    score_dict = score.to_dict()

    # Add component breakdown
    score_dict["breakdown"] = {
        "sod_violations": score.sod_score,
        "anomalous_behavior": score.anomaly_score,
        "over_provisioning": score.over_provisioning_score,
        "certification_failures": score.cert_failure_score,
        "peer_deviation": score.peer_deviation_score,
    }

    # Recent anomalous events
    recent_events_result = await db.execute(
        select(UserBehaviorEvent)
        .where(
            and_(
                UserBehaviorEvent.user_id == user_id,
                UserBehaviorEvent.is_anomalous == True,  # noqa: E712
            )
        )
        .order_by(desc(UserBehaviorEvent.created_at))
        .limit(5)
    )
    recent_events = recent_events_result.scalars().all()
    score_dict["recent_anomalies"] = [e.to_dict() for e in recent_events]

    return score_dict


@router.get("/history/{user_id}")
async def get_risk_score_history(
    user_id: UUID,
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(IdentityRiskHistory)
        .where(
            and_(
                IdentityRiskHistory.user_id == user_id,
                IdentityRiskHistory.tenant_id == current_user.tenant_id,
                IdentityRiskHistory.snapshot_date >= since,
            )
        )
        .order_by(IdentityRiskHistory.snapshot_date)
    )
    history = result.scalars().all()
    return {
        "user_id": str(user_id),
        "days": days,
        "items": [h.to_dict() for h in history],
    }


@router.get("/heatmap")
async def get_risk_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from backend.models.rbac import Department
    from backend.models.user import User as UserModel

    # Aggregate risk scores by department
    rows = await db.execute(
        select(
            UserModel.department_id,
            func.avg(RiskScore.overall_score).label("avg_score"),
            func.max(RiskScore.overall_score).label("max_score"),
            func.count(RiskScore.id).label("user_count"),
            func.sum(
                func.cast(RiskScore.risk_level == "critical", func.Integer if hasattr(func, "Integer") else func.count)
            ).label("critical_count"),
        )
        .join(RiskScore, RiskScore.user_id == UserModel.id)
        .where(
            and_(
                RiskScore.tenant_id == current_user.tenant_id,
                UserModel.tenant_id == current_user.tenant_id,
                UserModel.deleted_at.is_(None),
            )
        )
        .group_by(UserModel.department_id)
    )
    dept_data = rows.all()

    # Load department names
    dept_ids = [r[0] for r in dept_data if r[0]]
    dept_names: dict = {}
    if dept_ids:
        dept_result = await db.execute(
            select(Department.id, Department.name).where(Department.id.in_(dept_ids))
        )
        dept_names = {str(r[0]): r[1] for r in dept_result.all()}

    heatmap = []
    for row in dept_data:
        dept_id = str(row[0]) if row[0] else "unassigned"
        heatmap.append(
            {
                "department_id": dept_id,
                "department_name": dept_names.get(dept_id, "Unassigned"),
                "avg_risk_score": round(float(row[1] or 0), 1),
                "max_risk_score": round(float(row[2] or 0), 1),
                "user_count": row[3],
            }
        )

    heatmap.sort(key=lambda x: x["avg_risk_score"], reverse=True)
    return {"departments": heatmap, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/anomalies")
async def get_recent_anomalies(
    hours: int = Query(24, ge=1, le=168),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = select(UserBehaviorEvent).where(
        and_(
            UserBehaviorEvent.tenant_id == current_user.tenant_id,
            UserBehaviorEvent.is_anomalous == True,  # noqa: E712
            UserBehaviorEvent.created_at >= since,
        )
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(UserBehaviorEvent.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    events = rows.scalars().all()
    return {
        "items": [e.to_dict() for e in events],
        "total": total,
        "page": page,
        "per_page": per_page,
        "period_hours": hours,
    }


@router.get("/recommendations")
async def get_access_recommendations(
    rec_status: Optional[str] = Query(None, alias="status"),
    recommendation_type: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(AccessRecommendation).where(
        AccessRecommendation.tenant_id == current_user.tenant_id
    )
    if rec_status:
        query = query.where(AccessRecommendation.status == rec_status)
    else:
        query = query.where(AccessRecommendation.status == "pending")
    if recommendation_type:
        query = query.where(AccessRecommendation.recommendation_type == recommendation_type)
    if user_id:
        query = query.where(AccessRecommendation.user_id == user_id)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(AccessRecommendation.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    recs = rows.scalars().all()

    return {
        "items": [r.to_dict() for r in recs],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/recommendations/{rec_id}/accept")
async def accept_recommendation(
    rec_id: UUID,
    data: RecommendationAction,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AccessRecommendation).where(
            and_(
                AccessRecommendation.id == rec_id,
                AccessRecommendation.tenant_id == current_user.tenant_id,
            )
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if rec.status != "pending":
        raise HTTPException(status_code=400, detail=f"Recommendation already actioned: {rec.status}")

    rec.status = "accepted"
    await db.commit()

    return rec.to_dict()


@router.post("/recommendations/{rec_id}/reject")
async def reject_recommendation(
    rec_id: UUID,
    data: RecommendationAction,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AccessRecommendation).where(
            and_(
                AccessRecommendation.id == rec_id,
                AccessRecommendation.tenant_id == current_user.tenant_id,
            )
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if rec.status != "pending":
        raise HTTPException(status_code=400, detail=f"Recommendation already actioned: {rec.status}")

    rec.status = "rejected"
    await db.commit()

    return rec.to_dict()


@router.post("/recalculate/{user_id}")
async def recalculate_user_risk(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify user belongs to tenant
    user_result = await db.execute(
        select(User).where(
            and_(
                User.id == user_id,
                User.tenant_id == current_user.tenant_id,
                User.deleted_at.is_(None),
            )
        )
    )
    target_user = user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Queue Celery task for risk recalculation
    try:
        from backend.tasks.risk_tasks import recalculate_user_risk_task
        recalculate_user_risk_task.delay(str(user_id), str(current_user.tenant_id))
    except Exception:
        # Synchronous fallback
        try:
            from backend.services.risk_service import RiskService
            svc = RiskService(db)
            updated = await svc.update_risk_score(str(user_id), str(current_user.tenant_id))
            return {
                "success": True,
                "user_id": str(user_id),
                "message": "Risk score recalculated synchronously",
                "new_score": updated.overall_score if updated else None,
            }
        except Exception as e:
            return {"success": False, "user_id": str(user_id), "message": str(e)}

    return {
        "success": True,
        "user_id": str(user_id),
        "message": "Risk recalculation queued",
    }
