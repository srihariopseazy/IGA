from __future__ import annotations
import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class SODPolicy(Base):
    __tablename__ = "sod_policy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="active", index=True)
    risk_level = Column(String(50), nullable=False, default="high", index=True)
    version = Column(String(20), nullable=False, default="1.0")
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_sod_policy_tenant_status", "tenant_id", "status"),
        {"extend_existing": True},
    )


class SODRule(Base):
    __tablename__ = "sod_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_hard_block = Column(Boolean, nullable=False, default=False)
    conflicting_items = Column(JSONB, nullable=True, default=list)
    mitigation_control = Column(Text, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    violations = relationship("SODViolation", back_populates="sod_rule", lazy="select")

    __table_args__ = (
        Index("ix_sod_rules_tenant", "tenant_id"),
        {"extend_existing": True},
    )


class SODViolation(Base):
    deleted_at = None
    __tablename__ = "sod_violations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("sod_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="open", index=True)
    detected_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    mitigated_at = Column(DateTime(timezone=True), nullable=True)
    mitigation_notes = Column(Text, nullable=True)
    exception_approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_id = Column(UUID(as_uuid=True), nullable=True)
    conflict_details = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    sod_rule = relationship("SODRule", back_populates="violations")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_sod_violations_tenant_status", "tenant_id", "status"),
        Index("ix_sod_violations_user_status", "user_id", "status"),
        {"extend_existing": True},
    )
