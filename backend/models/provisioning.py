from __future__ import annotations
import uuid
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class ProvisioningTask(Base):
    deleted_at = None
    __tablename__ = "provisioning_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    task_type = Column(String(100), nullable=True)
    action = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default="pending", index=True)
    priority = Column(String(20), nullable=True, default="normal")
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True)
    entitlement_id = Column(UUID(as_uuid=True), nullable=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("access_requests.id", ondelete="SET NULL"), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    error_message = Column(Text, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSONB, nullable=True, default=dict)
    result = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_provisioning_tasks_tenant_status", "tenant_id", "status"),
        Index("ix_provisioning_tasks_user", "user_id"),
    )


class ProvisioningLog(Base):
    __tablename__ = "provisioning_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("provisioning_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(20), nullable=True)
    message = Column(Text, nullable=True)
    data = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
