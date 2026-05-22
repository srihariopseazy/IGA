from __future__ import annotations
import uuid
from sqlalchemy import Column, String, Float, Boolean, Date, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    request_number = Column(String(20), nullable=True)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    request_type = Column(String(30), nullable=False, default="grant", index=True)
    priority = Column(String(20), nullable=False, default="normal", index=True)
    justification = Column(Text, nullable=True)
    business_justification = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    risk_score = Column(Float, nullable=True)
    sod_violations = Column(JSONB, nullable=True, default=list)
    workflow_instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow_instances.id", ondelete="SET NULL"), nullable=True)
    request_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    sla_deadline = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    requester = relationship("User", foreign_keys=[requester_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
    items = relationship("AccessRequestItem", back_populates="access_request", lazy="select")
    approvals = relationship("Approval", back_populates="access_request", lazy="select")

    __table_args__ = (
        Index("ix_access_requests_tenant_status", "tenant_id", "status"),
        Index("ix_access_requests_requester_status", "requester_id", "status"),
        Index("ix_access_requests_target_status", "target_user_id", "status"),
    )


class AccessRequestItem(Base):
    __tablename__ = "access_request_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(String(50), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    entitlement_id = Column(UUID(as_uuid=True), nullable=True)
    application_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(50), nullable=False, default="pending", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    provisioning_task_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    access_request = relationship("AccessRequest", back_populates="items", foreign_keys=[request_id])

    __table_args__ = (
        Index("ix_access_request_items_request", "request_id"),
        {"extend_existing": True},
    )


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    step_order = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="pending", index=True)
    decision = Column(String(50), nullable=True)
    comments = Column(Text, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    escalated_to_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    access_request = relationship("AccessRequest", back_populates="approvals", foreign_keys=[request_id])
    approver = relationship("User", foreign_keys=[approver_id])

    __table_args__ = (
        Index("ix_approvals_request_status", "request_id", "status"),
        Index("ix_approvals_approver_status", "approver_id", "status"),
        {"extend_existing": True},
    )
