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
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class CertificationCampaign(Base):
    __tablename__ = "certification_campaign"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    campaign_type = Column(
        SAEnum(
            "manager", "app_owner", "role_owner", "entitlement",
            name="campaign_type_enum",
        ),
        nullable=False,
        index=True,
    )
    status = Column(
        SAEnum(
            "draft", "active", "paused", "completed", "cancelled",
            name="campaign_status_enum",
        ),
        nullable=False,
        default="draft",
        index=True,
    )
    scope_definition = Column(JSONB, nullable=True, default=dict)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    auto_revoke_on_expire = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    # Relationships
    items = relationship("CertificationItem", back_populates="campaign", lazy="select")
    reviewers = relationship("CertificationReviewer", back_populates="campaign", lazy="select")

    __table_args__ = (
        Index("ix_cert_campaign_tenant_status", "tenant_id", "status"),
        Index("ix_cert_campaign_tenant_type", "tenant_id", "campaign_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<CertificationCampaign id={self.id} name={self.name!r} status={self.status}>"
        )


class CertificationItem(Base):
    __tablename__ = "certification_item"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("certification_campaign.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type = Column(String(100), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reviewer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        SAEnum(
            "pending", "certified", "revoked", "escalated",
            name="certification_item_status_enum",
        ),
        nullable=False,
        default="pending",
        index=True,
    )
    decision_reason = Column(Text, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    evidence_url = Column(Text, nullable=True)

    # Relationships
    campaign = relationship("CertificationCampaign", back_populates="items")
    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    __table_args__ = (
        Index("ix_cert_item_campaign_status", "campaign_id", "status"),
        Index("ix_cert_item_reviewer_status", "reviewer_id", "status"),
        Index("ix_cert_item_user_campaign", "user_id", "campaign_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CertificationItem id={self.id} campaign_id={self.campaign_id} "
            f"status={self.status}>"
        )


class CertificationReviewer(Base):
    __tablename__ = "certification_reviewer"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("certification_campaign.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delegate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    scope = Column(JSONB, nullable=True, default=dict)
    items_assigned = Column(Integer, nullable=False, default=0)
    items_completed = Column(Integer, nullable=False, default=0)

    # Relationships
    campaign = relationship("CertificationCampaign", back_populates="reviewers")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    delegate = relationship("User", foreign_keys=[delegate_id])

    __table_args__ = (
        Index("ix_cert_reviewer_campaign_reviewer", "campaign_id", "reviewer_id", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<CertificationReviewer id={self.id} campaign_id={self.campaign_id} "
            f"reviewer_id={self.reviewer_id}>"
        )
