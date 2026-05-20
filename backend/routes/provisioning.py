from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.provisioning import ProvisioningLog, ProvisioningTask
from backend.models.user import User

router = APIRouter(prefix="/provisioning", tags=["Provisioning"])


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


@router.get("/tasks")
async def list_provisioning_tasks(
    task_status: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = Query(None),
    target_application_id: Optional[UUID] = Query(None),
    target_user_id: Optional[UUID] = Query(None),
    connector_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ProvisioningTask).where(
        ProvisioningTask.tenant_id == current_user.tenant_id
    )
    if task_status:
        query = query.where(ProvisioningTask.status == task_status)
    if task_type:
        query = query.where(ProvisioningTask.task_type == task_type)
    if target_application_id:
        query = query.where(ProvisioningTask.target_application_id == target_application_id)
    if target_user_id:
        query = query.where(ProvisioningTask.target_user_id == target_user_id)
    if connector_id:
        query = query.where(ProvisioningTask.connector_id == connector_id)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(desc(ProvisioningTask.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    tasks = rows.scalars().all()

    return {
        "items": [t.to_dict() for t in tasks],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/tasks/{task_id}")
async def get_provisioning_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProvisioningTask).where(
            and_(
                ProvisioningTask.id == task_id,
                ProvisioningTask.tenant_id == current_user.tenant_id,
            )
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Load task logs
    logs_result = await db.execute(
        select(ProvisioningLog)
        .where(ProvisioningLog.provisioning_task_id == task_id)
        .order_by(ProvisioningLog.created_at)
    )
    logs = logs_result.scalars().all()

    task_dict = task.to_dict()
    task_dict["logs"] = [log.to_dict() for log in logs]
    return task_dict


@router.post("/tasks/{task_id}/retry")
async def retry_provisioning_task(
    task_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProvisioningTask).where(
            and_(
                ProvisioningTask.id == task_id,
                ProvisioningTask.tenant_id == current_user.tenant_id,
            )
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("failed", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry task with status '{task.status}'. Only failed tasks can be retried.",
        )

    if task.attempt_count >= task.max_attempts:
        raise HTTPException(
            status_code=400,
            detail=f"Task has exceeded maximum retry attempts ({task.max_attempts})",
        )

    task.status = "pending"
    task.error_message = None
    task.scheduled_at = datetime.now(timezone.utc)
    await db.commit()

    # Queue the Celery retry task
    try:
        from backend.tasks.provisioning_tasks import execute_provisioning_task
        execute_provisioning_task.delay(str(task_id))
    except Exception:
        pass

    return {
        "success": True,
        "task_id": str(task_id),
        "message": "Task queued for retry",
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
    }


@router.get("/logs")
async def list_provisioning_logs(
    task_id: Optional[UUID] = Query(None),
    log_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ProvisioningLog).where(
        ProvisioningLog.tenant_id == current_user.tenant_id
    )
    if task_id:
        query = query.where(ProvisioningLog.provisioning_task_id == task_id)
    if log_status:
        query = query.where(ProvisioningLog.status == log_status)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(desc(ProvisioningLog.created_at)).offset((page - 1) * per_page).limit(per_page)
    rows = await db.execute(query)
    logs = rows.scalars().all()

    return {
        "items": [log.to_dict() for log in logs],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
