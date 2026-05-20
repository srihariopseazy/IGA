from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class ProvisioningTask(Base):
    __tablename__ = "provisioning_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type = Column(
        SAEnum(
            "create", "update", "delete", "enable", "disable",
            name="provisioning_task_type_enum",
        ),
        nullable=False,
        index=True,
    )
    target_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
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
            "pending", "running", "completed", "failed", "retrying",
            name="provisioning_task_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    payload = Column(JSONB, nullable=True, default=dict)
    result = Column(JSONB, nullable=True, default=dict)
    error_message = Column(Text, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    logs = relationship("ProvisioningLog", back_populates="provisioning_task", lazy="select")
    target_user = relationship("User", foreign_keys=[target_user_id])
    target_application = relationship("Application", foreign_keys=[target_application_id])

    __table_args__ = (
        Index("ix_provisioning_tasks_tenant_status", "tenant_id", "status"),
        Index("ix_provisioning_tasks_scheduled", "scheduled_at", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProvisioningTask id={self.id} task_type={self.task_type} "
            f"status={self.status}>"
        )


class ProvisioningLog(Base):
    __tablename__ = "provisioning_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    provisioning_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("provisioning_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action = Column(String(255), nullable=False)
    status = Column(
        SAEnum("success", "failure", "warning", name="provisioning_log_status_enum"),
        nullable=False,
        default="success",
        index=True,
    )
    request_payload = Column(JSONB, nullable=True, default=dict)
    response_payload = Column(JSONB, nullable=True, default=dict)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Relationships
    provisioning_task = relationship("ProvisioningTask", back_populates="logs")

    __table_args__ = (
        Index("ix_provisioning_logs_task", "provisioning_task_id"),
        Index("ix_provisioning_logs_tenant_created", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProvisioningLog id={self.id} provisioning_task_id={self.provisioning_task_id} "
            f"status={self.status}>"
        )
