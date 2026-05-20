import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.workflow import (
    ApprovalWorkflow,
    WorkflowStep,
    WorkflowInstance,
    WorkflowStepInstance,
)
from backend.models.access_request import AccessRequest
from backend.models.user import User, UserProfile
from backend.models.audit import AuditLog
from backend.utils.email import EmailService
from backend.config import settings

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService()

    async def start_workflow(
        self,
        workflow_id: str,
        reference_id: str,
        reference_type: str,
        context: dict,
        tenant_id: str,
    ) -> WorkflowInstance:
        # Load workflow definition
        result = await self.db.execute(
            select(ApprovalWorkflow)
            .options(selectinload(ApprovalWorkflow.steps))
            .where(
                and_(
                    ApprovalWorkflow.id == workflow_id,
                    ApprovalWorkflow.tenant_id == tenant_id,
                    ApprovalWorkflow.deleted_at.is_(None),
                )
            )
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Create WorkflowInstance
        instance = WorkflowInstance(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            tenant_id=tenant_id,
            reference_id=reference_id,
            reference_type=reference_type,
            status="in_progress",
            context=context,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(instance)
        await self.db.flush()

        # Sort steps by order
        sorted_steps = sorted(workflow.steps, key=lambda s: s.step_order)

        # Create step instances for all steps
        step_instances = []
        for step in sorted_steps:
            approver_id = await self.get_dynamic_approver(
                step.approver_type,
                context,
                tenant_id,
            )
            si = WorkflowStepInstance(
                id=uuid.uuid4(),
                workflow_instance_id=instance.id,
                workflow_step_id=step.id,
                tenant_id=tenant_id,
                step_order=step.step_order,
                approver_id=approver_id,
                status="pending" if step.step_order == sorted_steps[0].step_order else "waiting",
                due_at=datetime.now(timezone.utc) + timedelta(hours=step.sla_hours) if step.sla_hours else None,
            )
            self.db.add(si)
            step_instances.append(si)

        await self.db.flush()

        # Notify first approvers (step_order == first)
        first_step_instances = [si for si in step_instances if si.status == "pending"]
        for si in first_step_instances:
            if si.approver_id:
                approver = await self.db.get(User, si.approver_id)
                if approver:
                    try:
                        await self.email_service.send_approval_request(
                            approver.email,
                            {
                                "instance_id": str(instance.id),
                                "reference_type": reference_type,
                                "reference_id": reference_id,
                                "context": context,
                                "step_instance_id": str(si.id),
                            },
                        )
                    except Exception:
                        logger.warning("Failed to send approval email to %s", approver.email, exc_info=True)

        await self.db.commit()
        return instance

    async def process_step_completion(
        self,
        step_instance_id: str,
        action: str,
        completed_by: str,
        comments: str,
        tenant_id: str,
    ):
        # Load step instance
        result = await self.db.execute(
            select(WorkflowStepInstance).where(
                and_(
                    WorkflowStepInstance.id == step_instance_id,
                    WorkflowStepInstance.tenant_id == tenant_id,
                )
            )
        )
        step_instance = result.scalar_one_or_none()
        if not step_instance:
            raise ValueError("Step instance not found")

        if step_instance.status not in ("pending",):
            raise ValueError(f"Step is already {step_instance.status}")

        if action not in ("approve", "reject", "abstain"):
            raise ValueError(f"Invalid action: {action}")

        # Update step instance
        step_instance.status = "approved" if action == "approve" else ("rejected" if action == "reject" else "abstained")
        step_instance.completed_by = completed_by
        step_instance.comments = comments
        step_instance.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Load workflow instance
        instance = await self.db.get(WorkflowInstance, step_instance.workflow_instance_id)
        if not instance:
            raise ValueError("Workflow instance not found")

        # If rejected, fail the whole workflow
        if action == "reject":
            instance.status = "rejected"
            instance.completed_at = datetime.now(timezone.utc)
            await self._on_workflow_complete(instance, "rejected", tenant_id)
            await self.db.commit()
            return instance

        # Load all step instances for this workflow
        all_steps_result = await self.db.execute(
            select(WorkflowStepInstance).where(
                WorkflowStepInstance.workflow_instance_id == instance.id
            ).order_by(WorkflowStepInstance.step_order)
        )
        all_step_instances = all_steps_result.scalars().all()

        # Find the current step order
        current_order = step_instance.step_order

        # Check if all parallel steps at current order are done
        current_order_instances = [s for s in all_step_instances if s.step_order == current_order]
        all_current_done = all(s.status in ("approved", "abstained") for s in current_order_instances)

        if not all_current_done:
            # Still waiting for parallel approvers
            await self.db.commit()
            return instance

        # Find next pending step
        next_steps = [s for s in all_step_instances if s.step_order > current_order]
        if not next_steps:
            # Workflow complete
            instance.status = "approved"
            instance.completed_at = datetime.now(timezone.utc)
            await self._on_workflow_complete(instance, "approved", tenant_id)
        else:
            # Activate next step(s) at next order
            next_order = min(s.step_order for s in next_steps)
            next_order_instances = [s for s in next_steps if s.step_order == next_order]
            for nsi in next_order_instances:
                nsi.status = "pending"
                if nsi.approver_id:
                    approver = await self.db.get(User, nsi.approver_id)
                    if approver:
                        try:
                            await self.email_service.send_approval_request(
                                approver.email,
                                {
                                    "instance_id": str(instance.id),
                                    "step_instance_id": str(nsi.id),
                                    "context": instance.context,
                                },
                            )
                        except Exception:
                            logger.warning("Failed to notify next approver", exc_info=True)

        await self.db.commit()
        return instance

    async def _on_workflow_complete(
        self,
        instance: WorkflowInstance,
        outcome: str,
        tenant_id: str,
    ):
        if instance.reference_type == "access_request":
            result = await self.db.execute(
                select(AccessRequest).where(AccessRequest.id == instance.reference_id)
            )
            access_request = result.scalar_one_or_none()
            if access_request:
                access_request.status = "approved" if outcome == "approved" else "rejected"
                if outcome == "approved":
                    # Trigger provisioning
                    try:
                        from backend.services.provisioning_service import ProvisioningService
                        ps = ProvisioningService(self.db)
                        for role_id in (access_request.requested_roles or []):
                            await ps.create_provisioning_task(
                                task_type="grant_role",
                                target_user_id=str(access_request.user_id),
                                application_id=str(access_request.application_id) if access_request.application_id else None,
                                connector_id=None,
                                payload={"role_id": str(role_id)},
                                tenant_id=tenant_id,
                            )
                    except Exception:
                        logger.error("Failed to trigger provisioning after workflow approval", exc_info=True)

    async def escalate_overdue_steps(self, tenant_id: str):
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(WorkflowStepInstance).where(
                and_(
                    WorkflowStepInstance.tenant_id == tenant_id,
                    WorkflowStepInstance.status == "pending",
                    WorkflowStepInstance.due_at < now,
                    WorkflowStepInstance.escalated_at.is_(None),
                )
            )
        )
        overdue_steps = result.scalars().all()

        for step_instance in overdue_steps:
            # Find the approver's manager
            if step_instance.approver_id:
                approver_result = await self.db.execute(
                    select(User)
                    .options(selectinload(User.profile))
                    .where(User.id == step_instance.approver_id)
                )
                approver = approver_result.scalar_one_or_none()
                if approver and approver.profile and approver.profile.manager_id:
                    manager = await self.db.get(User, approver.profile.manager_id)
                    if manager:
                        try:
                            await self.email_service.send_escalation_notice(
                                manager.email,
                                {
                                    "step_instance_id": str(step_instance.id),
                                    "original_approver": approver.email,
                                    "overdue_since": step_instance.due_at.isoformat(),
                                },
                            )
                        except Exception:
                            logger.warning("Failed to send escalation notice", exc_info=True)
                        # Reassign to manager
                        step_instance.approver_id = manager.id

            step_instance.escalated_at = now
            step_instance.escalation_count = (step_instance.escalation_count or 0) + 1

        await self.db.commit()
        return len(overdue_steps)

    async def evaluate_auto_approve(
        self,
        access_request: AccessRequest,
        workflow: ApprovalWorkflow,
    ) -> bool:
        if not workflow.auto_approve_conditions:
            return False

        conditions = workflow.auto_approve_conditions

        # Check risk score threshold
        if "max_risk_score" in conditions:
            from backend.models.risk import RiskScore
            risk_result = await self.db.execute(
                select(RiskScore).where(
                    and_(
                        RiskScore.user_id == access_request.user_id,
                        RiskScore.tenant_id == access_request.tenant_id,
                    )
                )
            )
            risk = risk_result.scalar_one_or_none()
            if risk and risk.score > conditions["max_risk_score"]:
                return False

        # Check user attributes
        if "allowed_employment_types" in conditions:
            user_result = await self.db.execute(
                select(UserProfile).where(UserProfile.user_id == access_request.user_id)
            )
            profile = user_result.scalar_one_or_none()
            if profile and profile.employment_type not in conditions["allowed_employment_types"]:
                return False

        # Check if requesting low-risk roles only
        if "allowed_role_ids" in conditions:
            requested = set(str(r) for r in (access_request.requested_roles or []))
            allowed = set(str(r) for r in conditions["allowed_role_ids"])
            if not requested.issubset(allowed):
                return False

        return True

    async def get_dynamic_approver(
        self,
        approver_type: str,
        context: dict,
        tenant_id: str,
    ) -> Optional[str]:
        user_id = context.get("user_id") or context.get("requester_id")

        if approver_type == "manager":
            if not user_id:
                return None
            result = await self.db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            return str(profile.manager_id) if profile and profile.manager_id else None

        elif approver_type == "app_owner":
            app_id = context.get("application_id")
            if not app_id:
                return None
            from backend.models.application import Application
            result = await self.db.execute(
                select(Application).where(
                    and_(Application.id == app_id, Application.tenant_id == tenant_id)
                )
            )
            app = result.scalar_one_or_none()
            return str(app.owner_id) if app and app.owner_id else None

        elif approver_type == "role_owner":
            role_id = context.get("role_id") or (
                context.get("requested_roles", [None])[0] if context.get("requested_roles") else None
            )
            if not role_id:
                return None
            from backend.models.role import Role
            result = await self.db.execute(
                select(Role).where(and_(Role.id == role_id, Role.tenant_id == tenant_id))
            )
            role = result.scalar_one_or_none()
            return str(role.owner_id) if role and role.owner_id else None

        elif approver_type == "static":
            return context.get("static_approver_id")

        elif approver_type == "security_team":
            # Return first user with security admin role
            from backend.models.role import Role, UserRole
            result = await self.db.execute(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    and_(
                        Role.tenant_id == tenant_id,
                        Role.name == "security_admin",
                        UserRole.deleted_at.is_(None),
                    )
                )
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return str(row) if row else None

        return None

    async def simulate_workflow(
        self,
        workflow_id: str,
        context: dict,
        tenant_id: str,
    ) -> dict:
        result = await self.db.execute(
            select(ApprovalWorkflow)
            .options(selectinload(ApprovalWorkflow.steps))
            .where(
                and_(
                    ApprovalWorkflow.id == workflow_id,
                    ApprovalWorkflow.tenant_id == tenant_id,
                    ApprovalWorkflow.deleted_at.is_(None),
                )
            )
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise ValueError("Workflow not found")

        sorted_steps = sorted(workflow.steps, key=lambda s: s.step_order)

        steps_preview = []
        for step in sorted_steps:
            approver_id = await self.get_dynamic_approver(step.approver_type, context, tenant_id)
            approver_info = None
            if approver_id:
                approver = await self.db.get(User, approver_id)
                if approver:
                    approver_info = {
                        "id": str(approver.id),
                        "email": approver.email,
                        "display_name": approver.display_name,
                    }

            steps_preview.append(
                {
                    "step_order": step.step_order,
                    "step_name": step.name,
                    "approver_type": step.approver_type,
                    "approver": approver_info,
                    "sla_hours": step.sla_hours,
                    "is_optional": step.is_optional,
                }
            )

        # Check auto-approval eligibility
        auto_approve = False
        if context.get("access_request_id"):
            ar_result = await self.db.execute(
                select(AccessRequest).where(AccessRequest.id == context["access_request_id"])
            )
            ar = ar_result.scalar_one_or_none()
            if ar:
                auto_approve = await self.evaluate_auto_approve(ar, workflow)

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "steps": steps_preview,
            "total_steps": len(steps_preview),
            "auto_approve": auto_approve,
            "estimated_completion_hours": sum(
                s.get("sla_hours") or 24 for s in steps_preview
            ),
        }

    async def get_pending_approvals(
        self,
        approver_id: str,
        tenant_id: str,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        query = (
            select(WorkflowStepInstance)
            .where(
                and_(
                    WorkflowStepInstance.tenant_id == tenant_id,
                    WorkflowStepInstance.approver_id == approver_id,
                    WorkflowStepInstance.status == "pending",
                )
            )
            .order_by(WorkflowStepInstance.due_at.asc().nulls_last())
        )

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        offset = (page - 1) * per_page
        result = await self.db.execute(query.offset(offset).limit(per_page))
        items = result.scalars().all()

        return {
            "items": [
                {
                    "step_instance_id": str(s.id),
                    "workflow_instance_id": str(s.workflow_instance_id),
                    "step_order": s.step_order,
                    "status": s.status,
                    "due_at": s.due_at.isoformat() if s.due_at else None,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in items
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
