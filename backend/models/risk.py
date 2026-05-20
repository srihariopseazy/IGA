from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Float,
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


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overall_score = Column(Float, nullable=False, default=0.0)
    sod_score = Column(Float, nullable=False, default=0.0)
    anomaly_score = Column(Float, nullable=False, default=0.0)
    over_provisioning_score = Column(Float, nullable=False, default=0.0)
    cert_failure_score = Column(Float, nullable=False, default=0.0)
    peer_deviation_score = Column(Float, nullable=False, default=0.0)
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="risk_score_level_enum"),
        nullable=False,
        default="low",
        index=True,
    )
    factors = Column(JSONB, nullable=True, default=dict)
    last_calculated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    history = relationship("IdentityRiskHistory", back_populates="risk_score_ref", lazy="select")

    __table_args__ = (
        Index("ix_risk_scores_tenant_level", "tenant_id", "risk_level"),
        Index("ix_risk_scores_overall", "overall_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<RiskScore id={self.id} user_id={self.user_id} "
            f"overall_score={self.overall_score} risk_level={self.risk_level}>"
        )


class IdentityRiskHistory(Base):
    __tablename__ = "identity_risk_history"

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
    overall_score = Column(Float, nullable=False, default=0.0)
    risk_level = Column(
        SAEnum("low", "medium", "high", "critical", name="identity_risk_level_enum"),
        nullable=False,
        default="low",
        index=True,
    )
    snapshot_date = Column(DateTime(timezone=True), nullable=False, index=True)
    factors = Column(JSONB, nullable=True, default=dict)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    risk_score_ref = relationship(
        "RiskScore",
        back_populates="history",
        primaryjoin="IdentityRiskHistory.user_id == RiskScore.user_id",
        foreign_keys=[user_id],
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_identity_risk_history_user_date", "user_id", "snapshot_date"),
        Index("ix_identity_risk_history_tenant_date", "tenant_id", "snapshot_date"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<IdentityRiskHistory id={self.id} user_id={self.user_id} "
            f"snapshot_date={self.snapshot_date}>"
        )


class UserBehaviorEvent(Base):
    __tablename__ = "user_behavior_event"

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
    event_type = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True, index=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    ip_address = Column(String(45), nullable=True)
    device_fingerprint = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    anomaly_score = Column(Float, nullable=False, default=0.0)
    is_anomalous = Column(Boolean, nullable=False, default=False, index=True)
    metadata = Column(JSONB, nullable=True, default=dict)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_user_behavior_event_user_type", "user_id", "event_type"),
        Index("ix_user_behavior_event_tenant_created", "tenant_id", "created_at"),
        Index("ix_user_behavior_event_anomalous", "tenant_id", "is_anomalous"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<UserBehaviorEvent id={self.id} user_id={self.user_id} "
            f"event_type={self.event_type!r} is_anomalous={self.is_anomalous}>"
        )


class AccessRecommendation(Base):
    __tablename__ = "access_recommendation"

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
    recommendation_type = Column(
        SAEnum("grant", "revoke", name="recommendation_type_enum"),
        nullable=False,
        index=True,
    )
    item_type = Column(String(100), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    confidence_score = Column(Float, nullable=False, default=0.0)
    reason = Column(Text, nullable=True)
    peer_users = Column(JSONB, nullable=True, default=list)
    status = Column(
        SAEnum("pending", "accepted", "rejected", name="recommendation_status_enum"),
        nullable=False,
        default="pending",
        index=True,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_access_recommendation_user_status", "user_id", "status"),
        Index("ix_access_recommendation_tenant_type", "tenant_id", "recommendation_type"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<AccessRecommendation id={self.id} user_id={self.user_id} "
            f"recommendation_type={self.recommendation_type} status={self.status}>"
        )
