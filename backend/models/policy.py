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


class PolicyRule(Base):
    __tablename__ = "policy_rule"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    rule_type = Column(
        SAEnum(
            "abac", "rbac", "conditional", "geo", "device",
            name="policy_rule_type_enum",
        ),
        nullable=False,
        index=True,
    )
    conditions = Column(JSONB, nullable=True, default=dict)
    actions = Column(JSONB, nullable=True, default=dict)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_policy_rule_tenant_type_active", "tenant_id", "rule_type", "is_active"),
        Index("ix_policy_rule_tenant_priority", "tenant_id", "priority"),
    )

    def __repr__(self) -> str:
        return (
            f"<PolicyRule id={self.id} name={self.name!r} "
            f"rule_type={self.rule_type} priority={self.priority}>"
        )


class GeoRestriction(Base):
    __tablename__ = "geo_restriction"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country_code = Column(String(3), nullable=False, index=True)
    restriction_type = Column(
        SAEnum("block", "allow", name="geo_restriction_type_enum"),
        nullable=False,
        default="block",
        index=True,
    )
    reason = Column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_geo_restriction_tenant_country",
            "tenant_id",
            "country_code",
            "restriction_type",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<GeoRestriction id={self.id} tenant_id={self.tenant_id} "
            f"country_code={self.country_code!r} restriction_type={self.restriction_type}>"
        )


class DeviceTrustRecord(Base):
    __tablename__ = "device_trust_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_fingerprint = Column(String(255), nullable=False, index=True)
    device_name = Column(String(255), nullable=True)
    device_type = Column(String(100), nullable=True)
    os_name = Column(String(100), nullable=True)
    os_version = Column(String(100), nullable=True)
    is_trusted = Column(Boolean, nullable=False, default=False, index=True)
    is_compliant = Column(Boolean, nullable=False, default=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index(
            "ix_device_trust_user_fingerprint",
            "user_id",
            "device_fingerprint",
            unique=True,
        ),
        Index("ix_device_trust_tenant_trusted", "tenant_id", "is_trusted"),
    )

    def __repr__(self) -> str:
        return (
            f"<DeviceTrustRecord id={self.id} user_id={self.user_id} "
            f"device_fingerprint={self.device_fingerprint!r} is_trusted={self.is_trusted}>"
        )
