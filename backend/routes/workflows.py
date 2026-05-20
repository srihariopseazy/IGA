"""
Workflow routes for the IGA platform.
Handles workflow definitions, instances, and simulation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_permission
from backend.utils.audit import log_action
from backend.models.user import User
from backend.models.workflow import ApprovalWorkflow as Workflow, WorkflowInstance, WorkflowStep

router = APIRouter(prefix="/workflows", tags=["Workflows"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WorkflowStepSchema(BaseModel):
    step_order: int = Field(..., ge=1)
    name: str
    step_type: str = Field(..., pattern="^(approval|notification|auto_provision|condition|delay)$")
    approver_type: Optional[str] = Field(None, pattern="^(user|role|manager|owner|group)$")
    approver_id: Optional[str] = None
    approver_role: Optional[str] = None
    condition: Optional[Dict[str, Any]] = None
    timeout_hours: Optional[int] = Field(None, ge=1)
    escalation_hours: Optional[int] = None
    auto_approve_if_no_approver: bool = False

class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    trigger_type: str = Field(..., pattern="^(access_request|certification|offboarding|joiner|mover|manual)$")
    resource_types: List[str] = []
    steps: List[WorkflowStepSchema] = Field(..., min_items=1)
    is_default: bool = False
    priority_threshold: Optional[str] = None

class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[WorkflowStepSchema]] = None
    is_default: Optional[bool] = None
    priority_threshold: Optional[str] = None

class SimulateRequest(BaseModel):
    resource_type: str
    resource_id: str
    requester_id: str
    requested_for_id: Optional[str] = None
    priority: str = "normal"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workflow_to_dict(wf: Workflow) -> dict:
    return {
        "id": str(wf.id),
        "name": wf.name,
        "description": wf.description,
        "trigger_type": wf.trigger_type,
        "resource_types": wf.resource_types or [],
        "is_active": wf.is_active,
        "is_default": wf.is_default,
        "tenant_id": str(wf.tenant_id),
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
    }

def _instance_to_dict(inst: WorkflowInstance) -> dict:
    return {
        "id": str(inst.id),
        "workflow_id": str(inst.workflow_id),
        "status": inst.status,
        "trigger_type": inst.trigger_type,
        "resource_id": str(inst.resource_id) if inst.resource_id else None,
        "initiated_by": str(inst.initiated_by) if inst.initiated_by else None,
        "current_step": inst.current_step,
        "started_at": inst.started_at.isoformat() if inst.started_at else None,
        "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
        "created_at": inst.created_at.isoformat(),
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    trigger_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(require_permission("workflows:read")),
    db: AsyncSession = Depends(get_db),
):
    """List workflow definitions."""
    query = select(Workflow).where(Workflow.tenant_id == current_user.tenant_id)
    count_query = select(func.count(Workflow.id)).where(Workflow.tenant_id == current_user.tenant_id)

    if trigger_type:
        query = query.where(Workflow.trigger_type == trigger_type)
        count_query = count_query.where(Workflow.trigger_type == trigger_type)
    if is_active is not None:
        query = query.where(Workflow.is_active == is_active)
        count_query = count_query.where(Workflow.is_active == is_active)
    if search:
        filt = or_(Workflow.name.ilike(f"%{search}%"), Workflow.description.ilike(f"%{search}%"))
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(
        query.order_by(Workflow.name).offset((page - 1) * page_size).limit(page_size)
    )
    workflows = result.scalars().all()

    return {
        "items": [_workflow_to_dict(w) for w in workflows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("workflows:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a workflow definition."""
    existing = await db.execute(
        select(Workflow).where(
            and_(Workflow.name == body.name, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow name already exists")

    workflow = Workflow(
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        resource_types=body.resource_types,
        is_active=False,
        is_default=body.is_default,
        tenant_id=current_user.tenant_id,
        priority_threshold=body.priority_threshold,
    )
    db.add(workflow)
    await db.flush()

    for step_data in body.steps:
        step = WorkflowStep(
            workflow_id=workflow.id,
            step_order=step_data.step_order,
            name=step_data.name,
            step_type=step_data.step_type,
            approver_type=step_data.approver_type,
            approver_id=step_data.approver_id,
            approver_role=step_data.approver_role,
            condition=step_data.condition,
            timeout_hours=step_data.timeout_hours,
            escalation_hours=step_data.escalation_hours,
            auto_approve_if_no_approver=step_data.auto_approve_if_no_approver,
        )
        db.add(step)

    await db.commit()
    await db.refresh(workflow)

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "workflow_created", "workflow", str(workflow.id), {"name": workflow.name}
    )
    return _workflow_to_dict(workflow)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get workflow definition with steps."""
    result = await db.execute(
        select(Workflow)
        .where(and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id))
        .options(selectinload(Workflow.steps))
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    data = _workflow_to_dict(workflow)
    data["steps"] = [
        {
            "id": str(s.id),
            "step_order": s.step_order,
            "name": s.name,
            "step_type": s.step_type,
            "approver_type": s.approver_type,
            "approver_id": str(s.approver_id) if s.approver_id else None,
            "approver_role": s.approver_role,
            "timeout_hours": s.timeout_hours,
            "escalation_hours": s.escalation_hours,
            "auto_approve_if_no_approver": s.auto_approve_if_no_approver,
        }
        for s in sorted(workflow.steps, key=lambda x: x.step_order)
    ]
    return data


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("workflows:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update a workflow definition."""
    result = await db.execute(
        select(Workflow).where(
            and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if workflow.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit an active workflow. Deactivate first.",
        )

    update_data = body.dict(exclude_unset=True, exclude={"steps"})
    for key, value in update_data.items():
        setattr(workflow, key, value)
    workflow.updated_at = datetime.now(timezone.utc)

    if body.steps is not None:
        # Delete existing steps and recreate
        existing_steps = await db.execute(
            select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
        )
        for step in existing_steps.scalars().all():
            await db.delete(step)

        for step_data in body.steps:
            db.add(WorkflowStep(
                workflow_id=workflow.id,
                step_order=step_data.step_order,
                name=step_data.name,
                step_type=step_data.step_type,
                approver_type=step_data.approver_type,
                approver_id=step_data.approver_id,
                approver_role=step_data.approver_role,
                condition=step_data.condition,
                timeout_hours=step_data.timeout_hours,
                escalation_hours=step_data.escalation_hours,
                auto_approve_if_no_approver=step_data.auto_approve_if_no_approver,
            ))

    await db.commit()
    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "workflow_updated", "workflow", workflow_id, {}
    )
    return _workflow_to_dict(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("workflows:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a workflow."""
    result = await db.execute(
        select(Workflow).where(
            and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if workflow.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deactivate workflow before deleting")

    active_instances = await db.execute(
        select(func.count(WorkflowInstance.id)).where(
            and_(WorkflowInstance.workflow_id == workflow_id, WorkflowInstance.status.in_(["running", "pending"]))
        )
    )
    if active_instances.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete workflow with active instances",
        )

    await db.delete(workflow)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "workflow_deleted", "workflow", workflow_id, {"name": workflow.name}
    )


@router.post("/{workflow_id}/activate")
async def activate_workflow(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("workflows:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Activate a workflow."""
    result = await db.execute(
        select(Workflow).where(
            and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    workflow.is_active = True
    workflow.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "workflow_activated", "workflow", workflow_id, {}
    )
    return {"message": "Workflow activated", "workflow_id": workflow_id}


@router.post("/{workflow_id}/deactivate")
async def deactivate_workflow(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("workflows:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a workflow."""
    result = await db.execute(
        select(Workflow).where(
            and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    workflow.is_active = False
    workflow.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "workflow_deactivated", "workflow", workflow_id, {}
    )
    return {"message": "Workflow deactivated", "workflow_id": workflow_id}


@router.get("/{workflow_id}/instances")
async def list_workflow_instances(
    workflow_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(require_permission("workflows:read")),
    db: AsyncSession = Depends(get_db),
):
    """List instances of a workflow."""
    result = await db.execute(
        select(Workflow).where(
            and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    query = select(WorkflowInstance).where(WorkflowInstance.workflow_id == workflow_id)
    count_query = select(func.count(WorkflowInstance.id)).where(WorkflowInstance.workflow_id == workflow_id)

    if status_filter:
        query = query.where(WorkflowInstance.status == status_filter)
        count_query = count_query.where(WorkflowInstance.status == status_filter)

    total = (await db.execute(count_query)).scalar()
    inst_result = await db.execute(
        query.order_by(WorkflowInstance.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    instances = inst_result.scalars().all()

    return {
        "items": [_instance_to_dict(i) for i in instances],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/instances/{instance_id}")
async def get_workflow_instance(
    instance_id: str,
    current_user: User = Depends(require_permission("workflows:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed workflow instance with step statuses."""
    result = await db.execute(
        select(WorkflowInstance)
        .where(WorkflowInstance.id == instance_id)
        .options(selectinload(WorkflowInstance.workflow))
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow instance not found")

    data = _instance_to_dict(instance)
    data["context"] = instance.context or {}
    data["step_statuses"] = instance.step_statuses or []
    return data


@router.post("/{workflow_id}/simulate")
async def simulate_workflow(
    workflow_id: str,
    body: SimulateRequest,
    current_user: User = Depends(require_permission("workflows:read")),
    db: AsyncSession = Depends(get_db),
):
    """Simulate a workflow execution to preview approval steps."""
    result = await db.execute(
        select(Workflow)
        .where(and_(Workflow.id == workflow_id, Workflow.tenant_id == current_user.tenant_id))
        .options(selectinload(Workflow.steps))
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    requester = await db.execute(
        select(User).where(User.id == body.requester_id)
    )
    requester_user = requester.scalar_one_or_none()

    simulated_steps = []
    for step in sorted(workflow.steps, key=lambda x: x.step_order):
        approver_info = None
        if step.approver_type == "user" and step.approver_id:
            approver_q = await db.execute(select(User).where(User.id == step.approver_id))
            approver = approver_q.scalar_one_or_none()
            if approver:
                approver_info = {"id": str(approver.id), "name": f"{approver.first_name} {approver.last_name}"}
        elif step.approver_type == "manager" and requester_user and requester_user.manager_id:
            manager_q = await db.execute(select(User).where(User.id == requester_user.manager_id))
            manager = manager_q.scalar_one_or_none()
            if manager:
                approver_info = {"id": str(manager.id), "name": f"{manager.first_name} {manager.last_name}"}

        simulated_steps.append({
            "step_order": step.step_order,
            "name": step.name,
            "step_type": step.step_type,
            "approver_type": step.approver_type,
            "resolved_approver": approver_info,
            "timeout_hours": step.timeout_hours,
            "would_auto_approve": step.auto_approve_if_no_approver and approver_info is None,
        })

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.name,
        "simulation_input": body.dict(),
        "steps": simulated_steps,
        "estimated_approval_hours": sum(
            (s.get("timeout_hours") or 24) for s in simulated_steps
            if not s["would_auto_approve"]
        ),
    }
