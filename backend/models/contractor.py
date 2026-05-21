from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.database import Base


class ContractorProfile(Base):
    __tablename__ = "contractor_profile"

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
    company_name = Column(String(255), nullable=True)
    contract_start = Column(DateTime(timezone=True), nullable=True)
    contract_end = Column(DateTime(timezone=True), nullable=True, index=True)
    contract_number = Column(String(100), nullable=True, index=True)
    manager_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_name = Column(String(255), nullable=True)
    extension_count = Column(Integer, nullable=False, default=0)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    manager = relationship("User", foreign_keys=[manager_id])

    __table_args__ = (
        Index("ix_contractor_profile_tenant_end", "tenant_id", "contract_end"),
    )

    def __repr__(self) -> str:
        return (
            f"<ContractorProfile id={self.id} user_id={self.user_id} "
            f"company_name={self.company_name!r}>"
        )


class TemporaryAccessGrant(Base):
    __tablename__ = "temporary_access_grant"

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
    item_type = Column(String(100), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    justification = Column(Text, nullable=True)
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False, index=True)
    auto_revoke = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    approved_by_user = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        Index("ix_temp_access_grant_user_valid", "user_id", "valid_until"),
        Index("ix_temp_access_grant_tenant_valid", "tenant_id", "valid_until"),
    )

    def __repr__(self) -> str:
        return (
            f"<TemporaryAccessGrant id={self.id} user_id={self.user_id} "
            f"item_type={self.item_type!r} valid_until={self.valid_until}>"
        )
