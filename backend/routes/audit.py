import csv
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.audit import AuditLog
from backend.models.user import User

router = APIRouter(prefix="/audit", tags=["Audit"])


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


def _build_log_query(
    tenant_id,
    actor_id: Optional[str],
    action: Optional[str],
    resource_type: Optional[str],
    ip_address: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    result: Optional[str],
    risk_level: Optional[str],
):
    query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if actor_id:
        query = query.where(AuditLog.actor_id == user_id)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if ip_address:
        query = query.where(AuditLog.ip_address == ip_address)
    if start_time:
        query = query.where(AuditLog.created_at >= start_time)
    if end_time:
        query = query.where(AuditLog.created_at <= end_time)
    if result:
        query = query.where(AuditLog.outcome == result)
    if risk_level:
        query = query.where(AuditLog.outcome == risk_level)
    return query


@router.get("/logs")
async def list_audit_logs(
    actor_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    ip_address: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    result: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _build_log_query(
        current_user.tenant_id,
        actor_id,
        action,
        resource_type,
        ip_address,
        start_time,
        end_time,
        result,
        risk_level,
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()
    query = query.order_by(desc(AuditLog.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    logs = rows.scalars().all()
    return {
        "items": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/logs/export")
async def export_audit_logs(
    actor_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    ip_address: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    result: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    format: str = Query("csv", regex="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _build_log_query(
        current_user.tenant_id,
        actor_id,
        action,
        resource_type,
        ip_address,
        start_time,
        end_time,
        result,
        risk_level,
    )
    query = query.order_by(desc(AuditLog.created_at)).limit(50000)
    rows = await db.execute(query)
    logs = rows.scalars().all()

    if format == "json":
        data = json.dumps([log.to_dict() for log in logs], default=str).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit_logs.json"},
        )

    # CSV export
    output = io.StringIO()
    fieldnames = [
        "id",
        "tenant_id",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "ip_address",
        "result",
        "risk_level",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for log in logs:
        row = log.to_dict()
        writer.writerow({k: str(row.get(k, "")) for k in fieldnames})
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


@router.get("/logs/{log_id}")
async def get_audit_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AuditLog).where(
            and_(
                AuditLog.id == log_id,
                AuditLog.tenant_id == current_user.tenant_id,
            )
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    return log.to_dict()


@router.get("/security-events")
async def get_security_events(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        select(AuditLog)
        .where(
            and_(
                AuditLog.tenant_id == current_user.tenant_id,
                AuditLog.created_at >= since,
                AuditLog.outcome.in_(["high", "critical"]),
            )
        )
        .order_by(desc(AuditLog.created_at))
        .limit(500)
    )
    rows = await db.execute(query)
    logs = rows.scalars().all()
    return {
        "items": [log.to_dict() for log in logs],
        "total": len(logs),
        "period_hours": hours,
        "since": since.isoformat(),
    }


@router.get("/stats")
async def get_audit_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id

    total_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id)
    )
    total = total_result.scalar()

    # Counts by result
    by_result_rows = await db.execute(
        select(AuditLog.outcome, func.count(AuditLog.id))
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.outcome)
    )
    by_result = {row[0]: row[1] for row in by_result_rows.all()}

    # Counts by risk_level
    by_risk_rows = await db.execute(
        select(AuditLog.outcome, func.count(AuditLog.id))
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.outcome)
    )
    by_risk = {row[0]: row[1] for row in by_risk_rows.all()}

    # Top actions
    top_actions_rows = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("count"))
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.action)
        .order_by(desc("count"))
        .limit(10)
    )
    top_actions = [{"action": row[0], "count": row[1]} for row in top_actions_rows.all()]

    # Last 24h count
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    last_24h_result = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(AuditLog.tenant_id == tenant_id, AuditLog.created_at >= since_24h)
        )
    )
    last_24h = last_24h_result.scalar()

    return {
        "total_logs": total,
        "last_24h": last_24h,
        "by_result": by_result,
        "by_risk_level": by_risk,
        "top_actions": top_actions,
    }


@router.get("/analytics")
async def get_audit_analytics(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return analytics summary for the Analytics page."""
    from sqlalchemy import func, and_, select
    from backend.models.audit import AuditLog
    from datetime import timedelta

    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    # Total actions this month
    total_result = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(AuditLog.tenant_id == tenant_id, AuditLog.created_at >= month_ago)
        )
    )
    total_actions = total_result.scalar() or 0

    # Failed actions
    failed_result = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(
                AuditLog.tenant_id == tenant_id,
                AuditLog.created_at >= month_ago,
                AuditLog.outcome == "failure",
            )
        )
    )
    failed_actions = failed_result.scalar() or 0

    # Top actions
    top_actions_result = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("count"))
        .where(and_(AuditLog.tenant_id == tenant_id, AuditLog.created_at >= month_ago))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(5)
    )
    top_actions = [{"action": r[0], "count": r[1]} for r in top_actions_result.all()]

    return {
        "total_actions": total_actions,
        "failed_actions": failed_actions,
        "success_rate": round((total_actions - failed_actions) / total_actions * 100, 1) if total_actions else 100,
        "top_actions": top_actions,
        "period": "last_30_days",
    }
