from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class SODPolicy(Base):
    __tablename__ = "sod_policy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        SAEnum("active", "inactive", name="sod_policy_status_enum"),
        nullable=False,
        default="active",
        index=True,
    )
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="sod_policy_risk_level_enum"),
        nullable=False,
        default="high",
        index=True,
    )
    version = Column(String(20), nullable=False, default="1.0")
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    rules = relationship("SODRule", back_populates="policy", lazy="select")

    __table_args__ = (
        Index("ix_sod_policy_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<SODPolicy id={self.id} name={self.name!r} status={self.status}>"


class SODRule(Base):
    __tablename__ = "sod_rule"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    policy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sod_policy.id", ondelete="CASCADE"),
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
    role_id_1 = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id_2 = Column(
        UUID(as_uuid=True),
        ForeignKey("role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conflict_type = Column(String(100), nullable=False, default="exclusive")
    description = Column(Text, nullable=True)

    # Relationships
    policy = relationship("SODPolicy", back_populates="rules")
    role_1 = relationship("Role", foreign_keys=[role_id_1])
    role_2 = relationship("Role", foreign_keys=[role_id_2])
    violations = relationship("SODViolation", back_populates="sod_rule", lazy="select")

    __table_args__ = (
        Index("ix_sod_rule_policy", "policy_id"),
        Index("ix_sod_rule_roles", "role_id_1", "role_id_2"),
    )

    def __repr__(self) -> str:
        return (
            f"<SODRule id={self.id} name={self.name!r} "
            f"role_id_1={self.role_id_1} role_id_2={self.role_id_2}>"
        )


class SODViolation(Base):
    __tablename__ = "sod_violation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sod_rule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sod_rule.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id_1 = Column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False)
    role_id_2 = Column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=False)
    detection_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(
        SAEnum("open", "mitigated", "accepted", "resolved", name="sod_violation_status_enum"),
        nullable=False,
        default="open",
        index=True,
    )
    risk_score = Column(Float, nullable=True)
    mitigation_notes = Column(Text, nullable=True)
    mitigated_by = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    mitigated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    sod_rule = relationship("SODRule", back_populates="violations")
    user = relationship("User", foreign_keys=[user_id])
    mitigated_by_user = relationship("User", foreign_keys=[mitigated_by])

    __table_args__ = (
        Index("ix_sod_violation_tenant_status", "tenant_id", "status"),
        Index("ix_sod_violation_user_status", "user_id", "status"),
        Index("ix_sod_violation_rule_user", "sod_rule_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SODViolation id={self.id} user_id={self.user_id} "
            f"sod_rule_id={self.sod_rule_id} status={self.status}>"
        )
