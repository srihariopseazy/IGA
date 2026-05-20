from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Mapped

from backend.database import Base

if TYPE_CHECKING:
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    domain = Column(String(255), nullable=True, unique=True, index=True)
    logo_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_trial = Column(Boolean, nullable=False, default=False)
    trial_expires_at = Column(DateTime(timezone=True), nullable=True)
    plan_tier = Column(String(50), nullable=False, default="free")
    max_users = Column(Integer, nullable=False, default=100)
    settings = Column(JSONB, nullable=True, default=dict)
    metadata = Column(JSONB, nullable=True, default=dict)

    # Relationships
    branding = relationship(
        "TenantBranding", back_populates="tenant", uselist=False, lazy="select"
    )
    usage_metering = relationship(
        "TenantUsageMetering", back_populates="tenant", lazy="select"
    )

    __table_args__ = (
        Index("ix_tenants_slug_active", "slug", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} name={self.name!r} slug={self.slug!r}>"


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    logo_url = Column(Text, nullable=True)
    favicon_url = Column(Text, nullable=True)
    primary_color = Column(String(20), nullable=True)
    secondary_color = Column(String(20), nullable=True)
    company_name = Column(String(255), nullable=True)
    custom_domain = Column(String(255), nullable=True, unique=True)
    email_footer = Column(Text, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="branding")

    def __repr__(self) -> str:
        return f"<TenantBranding id={self.id} tenant_id={self.tenant_id}>"


class TenantUsageMetering(Base):
    __tablename__ = "tenant_usage_metering"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    api_calls = Column(BigInteger, nullable=False, default=0)
    active_users = Column(Integer, nullable=False, default=0)
    storage_bytes = Column(BigInteger, nullable=False, default=0)
    workflows_run = Column(Integer, nullable=False, default=0)

    # Relationships
    tenant = relationship("Tenant", back_populates="usage_metering")

    __table_args__ = (
        Index("ix_tenant_usage_tenant_period", "tenant_id", "period_start", "period_end"),
    )

    def __repr__(self) -> str:
        return (
            f"<TenantUsageMetering id={self.id} tenant_id={self.tenant_id} "
            f"period_start={self.period_start}>"
        )
