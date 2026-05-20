from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Float,
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


class AccessRequest(Base):
    __tablename__ = "access_request"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requester_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_type = Column(
        SAEnum("grant", "revoke", "modify", name="access_request_type_enum"),
        nullable=False,
        default="grant",
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "approved", "rejected", "cancelled", "expired",
            name="access_request_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    priority = Column(
        SAEnum("normal", "high", "emergency", name="access_request_priority_enum"),
        nullable=False,
        default="normal",
        index=True,
    )
    justification = Column(Text, nullable=True)
    business_justification = Column(Text, nullable=True)
    risk_score = Column(Float, nullable=True)
    workflow_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_instance.id", ondelete="SET NULL"),
        nullable=True,
    )
    sla_deadline = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
    items = relationship("AccessRequestItem", back_populates="access_request", lazy="select")
    approvals = relationship("Approval", back_populates="access_request", lazy="select")

    __table_args__ = (
        Index("ix_access_request_tenant_status", "tenant_id", "status"),
        Index("ix_access_request_requester_status", "requester_id", "status"),
        Index("ix_access_request_target_status", "target_user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AccessRequest id={self.id} type={self.request_type} status={self.status}>"
        )


class AccessRequestItem(Base):
    __tablename__ = "access_request_item"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    access_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("access_request.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type = Column(
        SAEnum("role", "entitlement", "application", name="request_item_type_enum"),
        nullable=False,
        index=True,
    )
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    action = Column(
        SAEnum("grant", "revoke", name="request_item_action_enum"),
        nullable=False,
        default="grant",
    )
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        SAEnum(
            "pending", "approved", "rejected", "provisioned", "failed",
            name="request_item_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )

    # Relationships
    access_request = relationship("AccessRequest", back_populates="items")

    __table_args__ = (
        Index("ix_access_request_item_request", "access_request_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AccessRequestItem id={self.id} item_type={self.item_type} item_id={self.item_id}>"
        )


class Approval(Base):
    __tablename__ = "approval"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("access_request.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_step_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_step.id", ondelete="SET NULL"),
        nullable=True,
    )
    approver_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delegated_to_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(
        SAEnum(
            "pending", "approved", "rejected", "delegated", "expired",
            name="approval_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    comments = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    access_request = relationship("AccessRequest", back_populates="approvals")
    approver = relationship("User", foreign_keys=[approver_id])
    delegated_to = relationship("User", foreign_keys=[delegated_to_id])

    __table_args__ = (
        Index("ix_approval_request_status", "access_request_id", "status"),
        Index("ix_approval_approver_status", "approver_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Approval id={self.id} access_request_id={self.access_request_id} "
            f"status={self.status}>"
        )
