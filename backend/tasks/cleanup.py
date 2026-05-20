import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete, update, and_

from backend.celery_app import celery_app
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _cleanup_expired_sessions_async() -> dict:
    """Remove expired user sessions from the database and Redis."""
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.user import UserSession

            now = datetime.now(timezone.utc)
            stmt = select(UserSession).where(
                and_(
                    UserSession.expires_at < now,
                    UserSession.is_active == True,
                )
            )
            result = await session.execute(stmt)
            expired_sessions = result.scalars().all()

            count = 0
            for sess in expired_sessions:
                sess.is_active = False
                sess.revoked_at = now
                # Blacklist the token in Redis so it can't be used even before TTL
                try:
                    from backend.utils.redis_client import redis_client
                    jti = getattr(sess, "jti", None)
                    if jti:
                        await redis_client.blacklist_token(jti, expire_seconds=60)
                except Exception as exc:
                    logger.warning("Failed to blacklist token for session %s: %s", sess.id, exc)
                count += 1

            await session.commit()
            logger.info("Cleaned up %d expired sessions", count)
            return {"cleaned_sessions": count}

        except Exception as exc:
            await session.rollback()
            logger.error("cleanup_expired_sessions error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.cleanup.cleanup_expired_sessions",
    queue="cleanup",
)
def cleanup_expired_sessions() -> dict:
    """Mark expired sessions as inactive and blacklist their tokens."""
    return _run_async(_cleanup_expired_sessions_async())


async def _cleanup_expired_tokens_async() -> dict:
    """Remove expired password reset, email verification, and magic link tokens."""
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.user import UserToken

            now = datetime.now(timezone.utc)
            stmt = delete(UserToken).where(UserToken.expires_at < now)
            result = await session.execute(stmt)
            deleted = result.rowcount
            await session.commit()
            logger.info("Cleaned up %d expired tokens", deleted)
            return {"deleted_tokens": deleted}

        except Exception as exc:
            await session.rollback()
            logger.error("cleanup_expired_tokens error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.cleanup.cleanup_expired_tokens",
    queue="cleanup",
)
def cleanup_expired_tokens() -> dict:
    """Delete expired one-time tokens (reset, verification, magic links)."""
    return _run_async(_cleanup_expired_tokens_async())


async def _archive_old_audit_logs_async(days: int = 365) -> dict:
    """
    Archive audit log entries older than `days` days to MinIO storage,
    then delete them from the database to keep the table manageable.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import AuditLog

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = select(AuditLog).where(AuditLog.created_at < cutoff).limit(10000)
            result = await session.execute(stmt)
            old_logs = result.scalars().all()

            if not old_logs:
                logger.info("No audit logs to archive older than %d days", days)
                return {"archived": 0, "deleted": 0}

            # Serialize logs to NDJSON
            import json
            lines = []
            ids_to_delete = []
            for log in old_logs:
                ids_to_delete.append(log.id)
                row = {
                    "id": str(log.id),
                    "tenant_id": str(getattr(log, "tenant_id", "")),
                    "user_id": str(getattr(log, "user_id", "")),
                    "action": getattr(log, "action", ""),
                    "resource_type": getattr(log, "resource_type", ""),
                    "resource_id": str(getattr(log, "resource_id", "")),
                    "created_at": str(getattr(log, "created_at", "")),
                    "details": getattr(log, "details", {}),
                }
                lines.append(json.dumps(row))

            archive_data = "\n".join(lines).encode("utf-8")

            from backend.config import settings
            from backend.utils.minio_client import minio_client
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            object_name = f"audit-archive/audit_logs_{timestamp}.ndjson"
            await minio_client.upload_file(
                bucket=settings.MINIO_BUCKET,
                object_name=object_name,
                data=archive_data,
                content_type="application/x-ndjson",
            )

            # Delete archived rows
            from sqlalchemy import delete as sa_delete
            del_stmt = sa_delete(AuditLog).where(AuditLog.id.in_(ids_to_delete))
            del_result = await session.execute(del_stmt)
            deleted = del_result.rowcount
            await session.commit()

            logger.info(
                "Archived %d audit log entries to %s and deleted from DB",
                len(old_logs), object_name,
            )
            return {"archived": len(old_logs), "deleted": deleted, "archive_path": object_name}

        except Exception as exc:
            await session.rollback()
            logger.error("archive_old_audit_logs error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.cleanup.archive_old_audit_logs",
    queue="cleanup",
)
def archive_old_audit_logs(days: int = 365) -> dict:
    """Archive audit logs older than `days` days to MinIO and remove from DB."""
    return _run_async(_archive_old_audit_logs_async(days))


async def _deactivate_expired_access_async() -> dict:
    """
    Find temporary role/entitlement assignments past their valid_until date
    and deactivate them, queuing deprovisioning tasks.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.rbac import UserRole

            now = datetime.now(timezone.utc)
            stmt = select(UserRole).where(
                and_(
                    UserRole.valid_until != None,
                    UserRole.valid_until < now,
                    UserRole.is_active == True,
                )
            )
            result = await session.execute(stmt)
            expired_assignments = result.scalars().all()

            deactivated = 0
            for assignment in expired_assignments:
                assignment.is_active = False
                assignment.deactivated_at = now
                assignment.deactivation_reason = "temporary_access_expired"
                deactivated += 1

                # Queue deprovisioning
                try:
                    from backend.tasks.provisioning import deprovision_user_access
                    # Build a deprovision task record would be needed here in a full implementation
                    logger.info(
                        "Expired assignment: user=%s role=%s tenant=%s",
                        assignment.user_id, assignment.role_id, assignment.tenant_id,
                    )
                    # Trigger risk score recalculation
                    from backend.tasks.risk_scoring import calculate_user_risk
                    calculate_user_risk.delay(str(assignment.user_id), str(assignment.tenant_id))
                except Exception as exc:
                    logger.warning(
                        "Failed to queue deprovisioning for user %s role %s: %s",
                        assignment.user_id, assignment.role_id, exc,
                    )

            await session.commit()
            logger.info("Deactivated %d expired access assignments", deactivated)
            return {"deactivated": deactivated}

        except Exception as exc:
            await session.rollback()
            logger.error("deactivate_expired_access error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.cleanup.deactivate_expired_access",
    queue="cleanup",
)
def deactivate_expired_access() -> dict:
    """Deactivate temporary role/entitlement assignments past their expiry date."""
    return _run_async(_deactivate_expired_access_async())
