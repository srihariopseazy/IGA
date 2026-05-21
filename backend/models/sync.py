from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class HRMSSyncJob(Base):
    __tablename__ = "hrms_sync_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "running", "completed", "failed", "partial",
            name="hrms_sync_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    records_processed = Column(Integer, nullable=False, default=0)
    records_created = Column(Integer, nullable=False, default=0)
    records_updated = Column(Integer, nullable=False, default=0)
    records_failed = Column(Integer, nullable=False, default=0)
    error_log = Column(JSONB, nullable=True, default=list)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_hrms_sync_job_tenant_status", "tenant_id", "status"),
        Index("ix_hrms_sync_job_tenant_created", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<HRMSSyncJob id={self.id} tenant_id={self.tenant_id} status={self.status}>"
        )


class LDAPSyncJob(Base):
    __tablename__ = "ldap_sync_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id = Column(
        UUID(as_uuid=True),
        ForeignKey("connector.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "running", "completed", "failed", "partial",
            name="ldap_sync_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    direction = Column(
        SAEnum("inbound", "outbound", "bidirectional", name="ldap_sync_direction_enum"),
        nullable=False,
        default="inbound",
        index=True,
    )
    records_processed = Column(Integer, nullable=False, default=0)
    errors = Column(JSONB, nullable=True, default=list)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    connector = relationship("Connector", foreign_keys=[connector_id])

    __table_args__ = (
        Index("ix_ldap_sync_job_tenant_status", "tenant_id", "status"),
        Index("ix_ldap_sync_job_connector", "connector_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<LDAPSyncJob id={self.id} tenant_id={self.tenant_id} "
            f"direction={self.direction} status={self.status}>"
        )


class SCIMSyncJob(Base):
    __tablename__ = "scim_sync_job"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id = Column(
        UUID(as_uuid=True),
        ForeignKey("connector.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "running", "completed", "failed", "partial",
            name="scim_sync_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    direction = Column(
        SAEnum("inbound", "outbound", "bidirectional", name="scim_sync_direction_enum"),
        nullable=False,
        default="inbound",
        index=True,
    )
    records_processed = Column(Integer, nullable=False, default=0)
    errors = Column(JSONB, nullable=True, default=list)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    connector = relationship("Connector", foreign_keys=[connector_id])

    __table_args__ = (
        Index("ix_scim_sync_job_tenant_status", "tenant_id", "status"),
        Index("ix_scim_sync_job_connector", "connector_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SCIMSyncJob id={self.id} tenant_id={self.tenant_id} "
            f"direction={self.direction} status={self.status}>"
        )
