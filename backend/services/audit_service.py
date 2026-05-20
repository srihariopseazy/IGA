import csv
import io
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_logs(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        ip_address: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        result: Optional[str] = None,
        risk_level: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        """Search audit logs with filters. Returns paginated results."""
        query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)

        if user_id:
            query = query.where(AuditLog.user_id == user_id)
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
            query = query.where(AuditLog.result == result)
        if risk_level:
            query = query.where(AuditLog.risk_level == risk_level)

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar() or 0

        query = (
            query.order_by(desc(AuditLog.created_at))
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = await self.db.execute(query)
        logs = rows.scalars().all()

        return {
            "items": [log.to_dict() for log in logs],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page > 0 else 0,
        }

    async def export_logs(
        self,
        tenant_id: str,
        export_format: str = "csv",
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        ip_address: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        result: Optional[str] = None,
        risk_level: Optional[str] = None,
        max_records: int = 50000,
    ) -> bytes:
        """
        Export audit logs in CSV or JSON format.
        Returns raw bytes ready to be streamed to the client.
        """
        query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)

        if user_id:
            query = query.where(AuditLog.user_id == user_id)
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
            query = query.where(AuditLog.result == result)
        if risk_level:
            query = query.where(AuditLog.risk_level == risk_level)

        query = query.order_by(desc(AuditLog.created_at)).limit(max_records)
        rows = await self.db.execute(query)
        logs = rows.scalars().all()

        if export_format == "json":
            data = [log.to_dict() for log in logs]
            return json.dumps(data, default=str).encode("utf-8")

        # Default: CSV
        output = io.StringIO()
        fieldnames = [
            "id",
            "tenant_id",
            "user_id",
            "action",
            "resource_type",
            "resource_id",
            "ip_address",
            "user_agent",
            "result",
            "risk_level",
            "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for log in logs:
            row = log.to_dict()
            writer.writerow({k: str(row.get(k, "") or "") for k in fieldnames})

        return output.getvalue().encode("utf-8")

    async def get_security_events(
        self,
        tenant_id: str,
        hours: int = 24,
        risk_levels: Optional[List[str]] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return recent high-risk security events."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        levels = risk_levels or ["high", "critical"]

        query = (
            select(AuditLog)
            .where(
                and_(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= since,
                    AuditLog.risk_level.in_(levels),
                )
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        rows = await self.db.execute(query)
        logs = rows.scalars().all()
        return [log.to_dict() for log in logs]

    async def get_audit_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Return aggregate statistics for the tenant's audit log."""
        # Total logs
        total_result = await self.db.execute(
            select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id)
        )
        total = total_result.scalar() or 0

        # By result
        by_result_rows = await self.db.execute(
            select(AuditLog.result, func.count(AuditLog.id))
            .where(AuditLog.tenant_id == tenant_id)
            .group_by(AuditLog.result)
        )
        by_result = {row[0]: row[1] for row in by_result_rows.all()}

        # By risk_level
        by_risk_rows = await self.db.execute(
            select(AuditLog.risk_level, func.count(AuditLog.id))
            .where(AuditLog.tenant_id == tenant_id)
            .group_by(AuditLog.risk_level)
        )
        by_risk = {row[0]: row[1] for row in by_risk_rows.all()}

        # Top actions (top 10 by count)
        top_actions_rows = await self.db.execute(
            select(AuditLog.action, func.count(AuditLog.id).label("cnt"))
            .where(AuditLog.tenant_id == tenant_id)
            .group_by(AuditLog.action)
            .order_by(desc("cnt"))
            .limit(10)
        )
        top_actions = [
            {"action": row[0], "count": row[1]} for row in top_actions_rows.all()
        ]

        # Last 24h count
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        last_24h_result = await self.db.execute(
            select(func.count(AuditLog.id)).where(
                and_(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= since_24h,
                )
            )
        )
        last_24h = last_24h_result.scalar() or 0

        # Last 7 days count
        since_7d = datetime.now(timezone.utc) - timedelta(days=7)
        last_7d_result = await self.db.execute(
            select(func.count(AuditLog.id)).where(
                and_(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= since_7d,
                )
            )
        )
        last_7d = last_7d_result.scalar() or 0

        # Top users by activity
        top_users_rows = await self.db.execute(
            select(AuditLog.user_id, func.count(AuditLog.id).label("cnt"))
            .where(
                and_(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.user_id.isnot(None),
                )
            )
            .group_by(AuditLog.user_id)
            .order_by(desc("cnt"))
            .limit(10)
        )
        top_users = [
            {"user_id": str(row[0]), "count": row[1]} for row in top_users_rows.all()
        ]

        return {
            "total_logs": total,
            "last_24h": last_24h,
            "last_7d": last_7d,
            "by_result": by_result,
            "by_risk_level": by_risk,
            "top_actions": top_actions,
            "top_users_by_activity": top_users,
        }

    async def log_event(
        self,
        tenant_id: str,
        user_id: Optional[str],
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        result: str = "success",
        risk_level: str = "low",
    ) -> AuditLog:
        """Create an audit log entry directly (convenience method)."""
        from backend.audit.audit_logger import audit_logger

        return await audit_logger.log(
            self.db,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            result=result,
            risk_level=risk_level,
        )
