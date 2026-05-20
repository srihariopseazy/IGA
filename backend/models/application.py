from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Column,
    String,
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


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    app_type = Column(String(100), nullable=False, default="web", index=True)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connector_id = Column(
        UUID(as_uuid=True),
        ForeignKey("connector.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="app_risk_level_enum"),
        nullable=False,
        default="low",
        index=True,
    )
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    metadata = Column(JSONB, nullable=True, default=dict)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    entitlements = relationship("Entitlement", back_populates="application", lazy="select")
    user_entitlements = relationship("UserEntitlement", back_populates="application", lazy="select")

    __table_args__ = (
        Index("ix_applications_tenant_name", "tenant_id", "name"),
        Index("ix_applications_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Application id={self.id} name={self.name!r}>"


class Entitlement(Base):
    __tablename__ = "app_entitlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    entitlement_type = Column(String(100), nullable=False, default="permission", index=True)
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="entitlement_risk_level_enum"),
        nullable=False,
        default="low",
        index=True,
    )
    requires_approval = Column(Boolean, nullable=False, default=False)
    is_requestable = Column(Boolean, nullable=False, default=True)
    metadata = Column(JSONB, nullable=True, default=dict)

    # Relationships
    application = relationship("Application", back_populates="entitlements")
    user_entitlements = relationship("UserEntitlement", back_populates="entitlement", lazy="select")

    __table_args__ = (
        Index("ix_app_entitlements_app_name", "application_id", "name"),
        Index("ix_app_entitlements_tenant_type", "tenant_id", "entitlement_type"),
    )

    def __repr__(self) -> str:
        return f"<Entitlement id={self.id} name={self.name!r} application_id={self.application_id}>"


class UserEntitlement(Base):
    __tablename__ = "app_account_entitlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entitlement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app_entitlements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_by = Column(UUID(as_uuid=True), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        SAEnum("active", "expired", "revoked", "pending", name="user_entitlement_status_enum"),
        nullable=False,
        default="active",
        index=True,
    )
    provisioning_status = Column(
        SAEnum("pending", "provisioned", "failed", "deprovisioned", name="provisioning_status_enum"),
        nullable=False,
        default="pending",
        index=True,
    )

    # Relationships
    entitlement = relationship("Entitlement", back_populates="user_entitlements")
    application = relationship("Application", back_populates="user_entitlements")

    __table_args__ = (
        Index("ix_app_account_entitlements_user_app", "user_id", "application_id"),
        Index("ix_app_account_entitlements_tenant_user", "tenant_id", "user_id"),
        Index("ix_app_account_entitlements_user_entitlement", "user_id", "entitlement_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserEntitlement id={self.id} user_id={self.user_id} "
            f"entitlement_id={self.entitlement_id} status={self.status}>"
        )
