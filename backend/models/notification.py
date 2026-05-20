from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type = Column(String(100), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    reference_type = Column(String(100), nullable=True, index=True)
    reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
        Index("ix_notifications_tenant_user", "tenant_id", "user_id"),
        Index("ix_notifications_reference", "reference_type", "reference_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} user_id={self.user_id} "
            f"notification_type={self.notification_type!r} is_read={self.is_read}>"
        )


class NotificationTemplate(Base):
    __tablename__ = "notification_template"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    template_type = Column(String(100), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text, nullable=True)
    variables = Column(JSONB, nullable=True, default=list)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        Index("ix_notification_template_type", "template_type"),
        Index("ix_notification_template_tenant_type", "tenant_id", "template_type"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationTemplate id={self.id} "
            f"template_type={self.template_type!r}>"
        )
