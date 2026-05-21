from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String(320), nullable=False, index=True)
    username = Column(String(150), nullable=True, index=True)
    password_hash = Column(Text, nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    display_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_locked = Column(Boolean, nullable=False, default=False, index=True)
    employee_id = Column(String(100), nullable=True, index=True)
    department = Column(String(255), nullable=True)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    is_superuser = Column(Boolean, nullable=False, default=False)
    email_verified = Column(Boolean, nullable=False, default=False)
    mfa_enabled = Column(Boolean, nullable=False, default=False)

    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    avatar_url = Column(Text, nullable=True)
    phone = Column(String(30), nullable=True)
    timezone = Column(String(64), nullable=True, default="UTC")
    locale = Column(String(10), nullable=True, default="en")


    # Relationships
    profile = relationship("UserProfile", back_populates="user", uselist=False, lazy="select")
    login_history = relationship("LoginHistory", back_populates="user", lazy="select")
    sessions = relationship("Session", back_populates="user", lazy="select")
    mfa_devices = relationship("MFADevice", back_populates="user", lazy="select")
    manager = relationship("User", remote_side="User.id", foreign_keys=[manager_id], lazy="select")

    __table_args__ = (
        Index("ix_users_tenant_email", "tenant_id", "email", unique=True),
        Index("ix_users_tenant_username", "tenant_id", "username"),
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )

    @property
    def status(self) -> str:
        """Computed status string for backward compatibility."""
        if not self.is_active:
            return "suspended"
        if self.is_locked:
            return "locked"
        return "active"

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_title = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    hire_date = Column(DateTime(timezone=True), nullable=True)
    exit_date = Column(DateTime(timezone=True), nullable=True)
    employment_type = Column(String(50), nullable=True, default="employee")
    cost_center = Column(String(100), nullable=True)
    manager_name = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    linkedin_url = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return f"<UserProfile id={self.id} user_id={self.user_id}>"


class LoginHistory(Base):
    __tablename__ = "login_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    device_info = Column(JSON, nullable=True)
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    failure_reason = Column(String(255), nullable=True)
    mfa_used = Column(Boolean, nullable=False, default=False)

    # Relationships
    user = relationship("User", back_populates="login_history")

    __table_args__ = (
        Index("ix_login_history_user_created", "user_id", "created_at"),
        Index("ix_login_history_tenant_created", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LoginHistory id={self.id} user_id={self.user_id} success={self.success}>"


class Session(Base):
    __tablename__ = "user_sessions"
    # Override base columns not in this table
    updated_at = None
    deleted_at = None
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash = Column(String(255), nullable=False, unique=True, index=True)
    refresh_token_hash = Column(String(255), nullable=True, unique=True, index=True)
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    device_info = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    mfa_verified = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Relationships
    user = relationship("User", back_populates="sessions")
    __table_args__ = (
        Index("ix_user_sessions_user_active", "user_id", "is_active"),
        Index("ix_user_sessions_tenant_active", "tenant_id", "is_active"),
    )
    def __repr__(self):
        return f"<Session id={self.id} user_id={self.user_id} is_active={self.is_active}>"


class MFADevice(Base):
    __tablename__ = "mfa_device"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_type = Column(String(50), nullable=False)
    name = Column(String(100), nullable=True)
    secret_encrypted = Column(Text, nullable=True)
    phone_number = Column(String(30), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="mfa_devices")

    __table_args__ = (
        Index("ix_mfa_device_user_type", "user_id", "device_type"),
    )

    def __repr__(self) -> str:
        return f"<MFADevice id={self.id} user_id={self.user_id} device_type={self.device_type}>"


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_token_hash = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PasswordResetToken id={self.id} user_id={self.user_id}>"


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_token"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_token_hash = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<EmailVerificationToken id={self.id} user_id={self.user_id}>"


class OTPCode(Base):
    __tablename__ = "otp_code"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = Column(String(255), nullable=False, index=True)
    purpose = Column(String(100), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_otp_code_user_purpose", "user_id", "purpose"),
    )

    def __repr__(self) -> str:
        return f"<OTPCode id={self.id} user_id={self.user_id} purpose={self.purpose!r}>"
