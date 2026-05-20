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


class OAuthClient(Base):
    __tablename__ = "oauth_client"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id = Column(String(255), nullable=False, unique=True, index=True)
    client_secret_hash = Column(Text, nullable=True)
    name = Column(String(255), nullable=False)
    redirect_uris = Column(JSONB, nullable=True, default=list)
    scopes = Column(JSONB, nullable=True, default=list)
    grant_types = Column(JSONB, nullable=True, default=list)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # Relationships
    tokens = relationship("OAuthToken", back_populates="client", lazy="select")

    __table_args__ = (
        Index("ix_oauth_client_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<OAuthClient id={self.id} client_id={self.client_id!r} name={self.name!r}>"


class OAuthToken(Base):
    __tablename__ = "oauth_token"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id = Column(
        UUID(as_uuid=True),
        ForeignKey("oauth_client.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    access_token_hash = Column(String(255), nullable=False, unique=True, index=True)
    refresh_token_hash = Column(String(255), nullable=True, unique=True, index=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    client = relationship("OAuthClient", back_populates="tokens")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_oauth_token_tenant_client", "tenant_id", "client_id"),
        Index("ix_oauth_token_user_expires", "user_id", "expires_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<OAuthToken id={self.id} client_id={self.client_id} "
            f"user_id={self.user_id} expires_at={self.expires_at}>"
        )
