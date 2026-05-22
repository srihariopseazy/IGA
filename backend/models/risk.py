from __future__ import annotations
import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET, UUID, JSONB
from sqlalchemy.orm import relationship
from backend.database import Base


class RiskScore(Base):
    deleted_at = None
    __tablename__ = "risk_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    score = Column(Float, nullable=False, default=0.0)
    level = Column(String(20), nullable=False, default="low", index=True)
    factors = Column(JSONB, nullable=True, default=dict)
    model_version = Column(String(50), nullable=True)
    calculated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_risk_scores_tenant_level", "tenant_id", "level"),
        Index("ix_risk_scores_entity", "entity_type", "entity_id"),
    )


class IdentityRiskHistory(Base):
    __tablename__ = "identity_risk_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    overall_score = Column(Float, nullable=False, default=0.0)
    risk_level = Column(String(20), nullable=False, default="low", index=True)
    snapshot_date = Column(DateTime(timezone=True), nullable=False, index=True)
    factors = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_identity_risk_history_user_date", "user_id", "snapshot_date"),
        {"extend_existing": True},
    )


class UserBehaviorEvent(Base):
    __tablename__ = "user_behavior_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    ip_address = Column(INET, nullable=True)
    device_fingerprint = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    anomaly_score = Column(Float, nullable=False, default=0.0)
    is_anomalous = Column(Boolean, nullable=False, default=False, index=True)
    extra_data = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_user_behavior_event_user_type", "user_id", "event_type"),
        {"extend_existing": True},
    )


class AccessRecommendation(Base):
    __tablename__ = "access_recommendation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    recommendation_type = Column(String(50), nullable=False, index=True)
    item_type = Column(String(100), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    confidence_score = Column(Float, nullable=False, default=0.0)
    reason = Column(Text, nullable=True)
    peer_users = Column(JSONB, nullable=True, default=list)
    status = Column(String(50), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
