import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from celery import Task
from sqlalchemy import select, update

from backend.celery_app import celery_app
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class ProvisioningTask(Task):
    abstract = True
    max_retries = 3
    default_retry_delay = 60  # seconds

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Provisioning task %s failed: %s", task_id, exc, exc_info=einfo)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning("Retrying provisioning task %s: %s", task_id, exc)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Provisioning task %s succeeded", task_id)


def _run_async(coro):
    """Run an async coroutine in a new event loop (for Celery sync context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _provision_user_access_async(task_id: str, tenant_id: str) -> dict:
    """Core async logic for provisioning user access."""
    async with AsyncSessionLocal() as session:
        try:
            # Lazy import to avoid circular deps
            from backend.models.application import ProvisioningTask as PTModel
            stmt = select(PTModel).where(
                PTModel.id == task_id,
                PTModel.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            task_record = result.scalar_one_or_none()

            if task_record is None:
                logger.error("Provisioning task %s not found for tenant %s", task_id, tenant_id)
                return {"status": "not_found"}

            # Mark as processing
            task_record.status = "processing"
            task_record.started_at = datetime.now(timezone.utc)
            await session.commit()

            connector_id = getattr(task_record, "connector_id", None)
            connector_type = getattr(task_record, "connector_type", "generic")
            operation = getattr(task_record, "operation", "grant")
            payload = getattr(task_record, "payload", {}) or {}

            logger.info(
                "Provisioning task %s: operation=%s connector=%s connector_type=%s",
                task_id, operation, connector_id, connector_type,
            )

            # Dispatch to connector
            success, error_msg = await _execute_connector_provisioning(
                connector_id, connector_type, operation, payload, tenant_id
            )

            if success:
                task_record.status = "completed"
                task_record.completed_at = datetime.now(timezone.utc)
                task_record.error_message = None
            else:
                task_record.status = "failed"
                task_record.error_message = error_msg

            await session.commit()

            # Notify user via WebSocket
            target_user_id = str(getattr(task_record, "target_user_id", ""))
            if target_user_id:
                try:
                    from backend.utils.websocket_manager import ws_manager
                    await ws_manager.send_provisioning_update(
                        tenant_id, target_user_id, task_id, task_record.status
                    )
                except Exception as ws_exc:
                    logger.warning("WS notification failed for task %s: %s", task_id, ws_exc)

            return {"status": task_record.status, "task_id": task_id}

        except Exception as exc:
            await session.rollback()
            logger.error("Error provisioning task %s: %s", task_id, exc, exc_info=True)
            raise


async def _execute_connector_provisioning(
    connector_id: Optional[str],
    connector_type: str,
    operation: str,
    payload: dict,
    tenant_id: str,
) -> tuple[bool, Optional[str]]:
    """Dispatch provisioning to the appropriate connector."""
    try:
        if connector_type == "ldap":
            return await _ldap_provision(connector_id, operation, payload, tenant_id)
        elif connector_type == "scim":
            return await _scim_provision(connector_id, operation, payload, tenant_id)
        elif connector_type == "rest":
            return await _rest_provision(connector_id, operation, payload, tenant_id)
        else:
            logger.info("Generic provisioning for connector_type=%s", connector_type)
            return True, None
    except Exception as exc:
        return False, str(exc)


async def _ldap_provision(connector_id, operation, payload, tenant_id) -> tuple[bool, Optional[str]]:
    logger.info("LDAP provisioning: op=%s connector=%s", operation, connector_id)
    # TODO: integrate with LDAP connector service
    return True, None


async def _scim_provision(connector_id, operation, payload, tenant_id) -> tuple[bool, Optional[str]]:
    logger.info("SCIM provisioning: op=%s connector=%s", operation, connector_id)
    # TODO: integrate with SCIM connector service
    return True, None


async def _rest_provision(connector_id, operation, payload, tenant_id) -> tuple[bool, Optional[str]]:
    logger.info("REST provisioning: op=%s connector=%s", operation, connector_id)
    # TODO: integrate with REST connector service
    return True, None


@celery_app.task(
    bind=True,
    base=ProvisioningTask,
    name="backend.tasks.provisioning.provision_user_access",
    queue="provisioning",
)
def provision_user_access(self, task_id: str, tenant_id: str):
    """Grant access for a user as defined by the provisioning task record."""
    try:
        return _run_async(_provision_user_access_async(task_id, tenant_id))
    except Exception as exc:
        logger.error("provision_user_access failed for task %s: %s", task_id, exc)
        raise self.retry(exc=exc)


async def _deprovision_user_access_async(task_id: str, tenant_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import ProvisioningTask as PTModel
            stmt = select(PTModel).where(
                PTModel.id == task_id,
                PTModel.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            task_record = result.scalar_one_or_none()

            if task_record is None:
                logger.error("Deprovision task %s not found", task_id)
                return {"status": "not_found"}

            task_record.status = "processing"
            task_record.started_at = datetime.now(timezone.utc)
            await session.commit()

            connector_id = getattr(task_record, "connector_id", None)
            connector_type = getattr(task_record, "connector_type", "generic")
            payload = getattr(task_record, "payload", {}) or {}

            success, error_msg = await _execute_connector_provisioning(
                connector_id, connector_type, "revoke", payload, tenant_id
            )

            task_record.status = "completed" if success else "failed"
            task_record.completed_at = datetime.now(timezone.utc) if success else None
            task_record.error_message = error_msg
            await session.commit()

            return {"status": task_record.status, "task_id": task_id}
        except Exception as exc:
            await session.rollback()
            raise


@celery_app.task(
    bind=True,
    base=ProvisioningTask,
    name="backend.tasks.provisioning.deprovision_user_access",
    queue="provisioning",
)
def deprovision_user_access(self, task_id: str, tenant_id: str):
    """Revoke access for a user as defined by the provisioning task record."""
    try:
        return _run_async(_deprovision_user_access_async(task_id, tenant_id))
    except Exception as exc:
        logger.error("deprovision_user_access failed for task %s: %s", task_id, exc)
        raise self.retry(exc=exc)


async def _retry_failed_tasks_async() -> dict:
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import ProvisioningTask as PTModel
            stmt = select(PTModel).where(
                PTModel.status == "failed",
                PTModel.retry_count < 3,
            )
            result = await session.execute(stmt)
            failed_tasks = result.scalars().all()

            retried = 0
            for task_record in failed_tasks:
                try:
                    task_record.retry_count = (getattr(task_record, "retry_count", 0) or 0) + 1
                    task_record.status = "queued"
                    operation = getattr(task_record, "operation", "grant")
                    if operation == "revoke":
                        deprovision_user_access.delay(str(task_record.id), str(task_record.tenant_id))
                    else:
                        provision_user_access.delay(str(task_record.id), str(task_record.tenant_id))
                    retried += 1
                except Exception as exc:
                    logger.error("Failed to retry task %s: %s", task_record.id, exc)

            await session.commit()
            logger.info("Retried %d failed provisioning tasks", retried)
            return {"retried": retried}
        except Exception as exc:
            await session.rollback()
            logger.error("retry_failed_tasks error: %s", exc)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.provisioning.retry_failed_tasks",
    queue="provisioning",
)
def retry_failed_tasks():
    """Find and re-queue failed provisioning tasks that have not exceeded max retries."""
    return _run_async(_retry_failed_tasks_async())


async def _verify_provisioning_async(task_id: str, tenant_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import ProvisioningTask as PTModel
            stmt = select(PTModel).where(
                PTModel.id == task_id,
                PTModel.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            task_record = result.scalar_one_or_none()
            if task_record is None:
                return {"verified": False, "reason": "task_not_found"}

            status = getattr(task_record, "status", "unknown")
            logger.info("Verifying provisioning task %s: status=%s", task_id, status)
            return {
                "verified": status == "completed",
                "status": status,
                "task_id": task_id,
            }
        except Exception as exc:
            logger.error("verify_provisioning error for task %s: %s", task_id, exc)
            return {"verified": False, "error": str(exc)}


@celery_app.task(
    name="backend.tasks.provisioning.verify_provisioning",
    queue="provisioning",
)
def verify_provisioning(task_id: str, tenant_id: str) -> dict:
    """Verify that a provisioning task completed successfully."""
    return _run_async(_verify_provisioning_async(task_id, tenant_id))
