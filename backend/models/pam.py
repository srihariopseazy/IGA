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
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class PrivilegedAccount(Base):
    __tablename__ = "privileged_account"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_name = Column(String(255), nullable=False)
    account_type = Column(
        SAEnum("admin", "root", "service", "shared", name="privileged_account_type_enum"),
        nullable=False,
        index=True,
    )
    system_name = Column(String(255), nullable=False, index=True)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_rotation_at = Column(DateTime(timezone=True), nullable=True)
    is_vaulted = Column(Boolean, nullable=False, default=False, index=True)
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="privileged_account_risk_enum"),
        nullable=False,
        default="high",
        index=True,
    )

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    pam_sessions = relationship("PAMSession", back_populates="privileged_account", lazy="select")
    break_glass_requests = relationship(
        "BreakGlassRequest", back_populates="privileged_account", lazy="select"
    )

    __table_args__ = (
        Index("ix_privileged_account_tenant_system", "tenant_id", "system_name"),
        Index("ix_privileged_account_tenant_type", "tenant_id", "account_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<PrivilegedAccount id={self.id} account_name={self.account_name!r} "
            f"system_name={self.system_name!r}>"
        )


class PAMSession(Base):
    __tablename__ = "pam_session"

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
    privileged_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("privileged_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_type = Column(String(100), nullable=False, default="interactive")
    justification = Column(Text, nullable=True)
    status = Column(
        SAEnum("active", "expired", "terminated", name="pam_session_status_enum"),
        nullable=False,
        default="active",
        index=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    terminated_at = Column(DateTime(timezone=True), nullable=True)
    recording_url = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    privileged_account = relationship("PrivilegedAccount", back_populates="pam_sessions")

    __table_args__ = (
        Index("ix_pam_session_tenant_status", "tenant_id", "status"),
        Index("ix_pam_session_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<PAMSession id={self.id} user_id={self.user_id} "
            f"privileged_account_id={self.privileged_account_id} status={self.status}>"
        )


class BreakGlassRequest(Base):
    __tablename__ = "break_glass_request"

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
    privileged_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("privileged_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    justification = Column(Text, nullable=False)
    status = Column(
        SAEnum(
            "pending", "approved", "active", "expired",
            name="break_glass_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    privileged_account = relationship("PrivilegedAccount", back_populates="break_glass_requests")
    approved_by_user = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        Index("ix_break_glass_tenant_status", "tenant_id", "status"),
        Index("ix_break_glass_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<BreakGlassRequest id={self.id} user_id={self.user_id} status={self.status}>"
        )
