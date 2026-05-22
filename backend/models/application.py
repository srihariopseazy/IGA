from __future__ import annotations
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    type = Column(String(100), nullable=True, index=True)
    category = Column(String(100), nullable=True)
    logo_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_privileged = Column(Boolean, nullable=False, default=False)
    requires_approval = Column(Boolean, nullable=False, default=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    connector_type = Column(String(100), nullable=True)
    connector_config = Column(JSONB, nullable=True, default=dict)
    provisioning_config = Column(JSONB, nullable=True, default=dict)
    app_metadata = Column("metadata", JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("ix_applications_tenant_name", "tenant_id", "name"),
        Index("ix_applications_tenant_active", "tenant_id", "is_active"),
    )


class Entitlement(Base):
    __tablename__ = "app_entitlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    type = Column(String(100), nullable=True)
    is_privileged = Column(Boolean, nullable=False, default=False)
    requires_justification = Column(Boolean, nullable=False, default=False)
    max_grant_duration_days = Column(String(50), nullable=True)
    risk_level = Column(String(50), nullable=True, default="low")
    external_id = Column(String(255), nullable=True)
    ent_metadata = Column("metadata", JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    application = relationship("Application", foreign_keys=[application_id])

    __table_args__ = (
        Index("ix_app_entitlements_tenant", "tenant_id"),
        Index("ix_app_entitlements_application", "application_id"),
    )


class UserEntitlement(Base):
    __tablename__ = "app_account_entitlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    app_account_id = Column(UUID(as_uuid=True), nullable=True)
    entitlement_id = Column(UUID(as_uuid=True), ForeignKey("app_entitlements.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    granted_by_id = Column(UUID(as_uuid=True), nullable=True)
    grant_reason = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    ue_metadata = Column("metadata", JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
