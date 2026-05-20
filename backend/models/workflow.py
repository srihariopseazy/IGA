from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflow"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    workflow_type = Column(String(100), nullable=False, index=True)
    definition = Column(JSONB, nullable=True, default=dict)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    steps = relationship("WorkflowStep", back_populates="workflow", lazy="select")
    instances = relationship("WorkflowInstance", back_populates="workflow", lazy="select")

    __table_args__ = (
        Index("ix_approval_workflow_tenant_type", "tenant_id", "workflow_type"),
        Index("ix_approval_workflow_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<ApprovalWorkflow id={self.id} name={self.name!r} version={self.version}>"


class WorkflowStep(Base):
    __tablename__ = "workflow_step"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    step_type = Column(
        SAEnum(
            "approval", "notification", "condition", "action",
            name="workflow_step_type_enum",
        ),
        nullable=False,
        default="approval",
        index=True,
    )
    approver_type = Column(
        SAEnum(
            "specific_user", "manager", "role_owner", "app_owner", "dynamic",
            name="workflow_approver_type_enum",
        ),
        nullable=True,
    )
    approver_id = Column(UUID(as_uuid=True), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    parallel_group = Column(Integer, nullable=True)
    conditions = Column(JSONB, nullable=True, default=dict)
    escalation_hours = Column(Integer, nullable=True)
    auto_approve_conditions = Column(JSONB, nullable=True, default=dict)

    # Relationships
    workflow = relationship("ApprovalWorkflow", back_populates="steps")
    step_instances = relationship("WorkflowStepInstance", back_populates="workflow_step", lazy="select")

    __table_args__ = (
        Index("ix_workflow_step_workflow_order", "workflow_id", "order_index"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowStep id={self.id} name={self.name!r} "
            f"step_type={self.step_type} order={self.order_index}>"
        )


class WorkflowInstance(Base):
    __tablename__ = "workflow_instance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval_workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reference_type = Column(String(100), nullable=False, index=True)
    status = Column(
        SAEnum(
            "active", "completed", "failed", "cancelled",
            name="workflow_instance_status_enum",
        ),
        nullable=False,
        default="active",
        index=True,
    )
    current_step = Column(Integer, nullable=True)
    context = Column(JSONB, nullable=True, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow = relationship("ApprovalWorkflow", back_populates="instances")
    step_instances = relationship("WorkflowStepInstance", back_populates="workflow_instance", lazy="select")

    __table_args__ = (
        Index("ix_workflow_instance_reference", "reference_id", "reference_type"),
        Index("ix_workflow_instance_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowInstance id={self.id} workflow_id={self.workflow_id} "
            f"status={self.status}>"
        )


class WorkflowStepInstance(Base):
    __tablename__ = "workflow_step_instance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    workflow_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_instance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_step_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_step.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "active", "completed", "skipped", "failed",
            name="workflow_step_instance_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    assignee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completed_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    comments = Column(Text, nullable=True)

    # Relationships
    workflow_instance = relationship("WorkflowInstance", back_populates="step_instances")
    workflow_step = relationship("WorkflowStep", back_populates="step_instances")
    assignee = relationship("User", foreign_keys=[assignee_id])
    completed_by = relationship("User", foreign_keys=[completed_by_id])

    __table_args__ = (
        Index("ix_workflow_step_instance_instance", "workflow_instance_id"),
        Index("ix_workflow_step_instance_assignee_status", "assignee_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowStepInstance id={self.id} "
            f"workflow_instance_id={self.workflow_instance_id} status={self.status}>"
        )
