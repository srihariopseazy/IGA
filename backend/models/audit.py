from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = Column(String(255), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True, index=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    details = Column(JSONB, nullable=True, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    result = Column(
        SAEnum("success", "failure", "error", name="audit_log_result_enum"),
        nullable=False,
        default="success",
        index=True,
    )
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="audit_log_risk_level_enum"),
        nullable=True,
        index=True,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_audit_log_tenant_action", "tenant_id", "action"),
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_user_created", "user_id", "created_at"),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
        {
            "postgresql_partition_by": "RANGE (created_at)",
        },
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"result={self.result} user_id={self.user_id}>"
        )


class ComplianceReport(Base):
    __tablename__ = "compliance_report"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_type = Column(
        SAEnum(
            "sox", "hipaa", "gdpr", "iso27001", "pci_dss",
            name="compliance_report_type_enum",
        ),
        nullable=False,
        index=True,
    )
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(
        SAEnum(
            "generating", "completed", "failed",
            name="compliance_report_status_enum",
        ),
        nullable=False,
        default="generating",
        index=True,
    )
    file_url = Column(Text, nullable=True)
    generated_by = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    generated_by_user = relationship("User", foreign_keys=[generated_by])

    __table_args__ = (
        Index("ix_compliance_report_tenant_type", "tenant_id", "report_type"),
        Index("ix_compliance_report_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ComplianceReport id={self.id} report_type={self.report_type} "
            f"status={self.status}>"
        )
