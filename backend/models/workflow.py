import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class ApprovalWorkflow(Base):
    __tablename__ = "workflow_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    type = Column(String(50), nullable=True)
    workflow_type = Column(String(50), nullable=True)
    trigger_type = Column(String(50), nullable=True)
    trigger_config = Column(JSONB, nullable=True, default=dict)
    steps = Column(JSONB, nullable=True, default=list)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    instances = relationship("WorkflowInstance", back_populates="workflow", lazy="select")


class WorkflowStep(Base):
    __tablename__ = "workflow_step"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    name = Column(String(255), nullable=False)
    step_type = Column(String(100), nullable=True)
    approver_type = Column(String(100), nullable=True)
    approver_id = Column(UUID(as_uuid=True), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    parallel_group = Column(Integer, nullable=True)
    conditions = Column(JSONB, nullable=True, default=dict)
    escalation_hours = Column(Integer, nullable=True)
    auto_approve_conditions = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    step_instances = relationship("WorkflowStepInstance", back_populates="workflow_step", lazy="select")


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    definition_id = Column(UUID(as_uuid=True), ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), nullable=True)
    current_step = Column(Integer, nullable=True)
    context = Column(JSONB, nullable=True, default=dict)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    workflow = relationship("ApprovalWorkflow", back_populates="instances")
    step_instances = relationship("WorkflowStepInstance", back_populates="workflow_instance", lazy="select")


class WorkflowStepInstance(Base):
    __tablename__ = "workflow_step_instance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    workflow_instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False)
    workflow_step_id = Column(UUID(as_uuid=True), ForeignKey("workflow_step.id", ondelete="SET NULL"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(50), nullable=True)
    assignee_id = Column(UUID(as_uuid=True), nullable=True)
    completed_by_id = Column(UUID(as_uuid=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    workflow_instance = relationship("WorkflowInstance", back_populates="step_instances")
    workflow_step = relationship("WorkflowStep", back_populates="step_instances")
