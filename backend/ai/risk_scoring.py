from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.risk import RiskScore, UserBehaviorEvent
from backend.models.sod import SODViolation
from backend.models.certification import CertificationItem


WEIGHT_SOD = 0.30
WEIGHT_ANOMALY = 0.20
WEIGHT_OVER_PROV = 0.15
WEIGHT_CERT_FAIL = 0.20
WEIGHT_PEER_DEV = 0.15


class RiskScorer:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute_user_risk(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> float:
        sod_score = await self._sod_score(tenant_id, user_id)
        anomaly_score = await self._anomaly_score(tenant_id, user_id)
        over_prov_score = await self._over_provisioning_score(tenant_id, user_id)
        cert_fail_score = await self._cert_failure_score(tenant_id, user_id)
        peer_score = await self._peer_deviation_score(tenant_id, user_id)

        composite = (
            sod_score * WEIGHT_SOD
            + anomaly_score * WEIGHT_ANOMALY
            + over_prov_score * WEIGHT_OVER_PROV
            + cert_fail_score * WEIGHT_CERT_FAIL
            + peer_score * WEIGHT_PEER_DEV
        )
        return min(round(composite, 2), 100.0)

    async def _sod_score(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> float:
        result = await self.db.execute(
            select(func.count(SODViolation.id)).where(
                SODViolation.tenant_id == tenant_id,
                SODViolation.user_id == user_id,
                SODViolation.resolved_at.is_(None),
            )
        )
        count = result.scalar() or 0
        return min(count * 25.0, 100.0)

    async def _anomaly_score(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> float:
        if not SKLEARN_AVAILABLE:
            return 0.0

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        result = await self.db.execute(
            select(UserBehaviorEvent).where(
                UserBehaviorEvent.tenant_id == tenant_id,
                UserBehaviorEvent.user_id == user_id,
                UserBehaviorEvent.created_at >= cutoff,
            ).order_by(UserBehaviorEvent.created_at)
        )
        events = result.scalars().all()

        if len(events) < 10:
            return 0.0

        features = np.array([
            [
                e.hour_of_day if hasattr(e, "hour_of_day") else 12,
                e.day_of_week if hasattr(e, "day_of_week") else 1,
            ]
            for e in events
        ])

        model = IsolationForest(contamination=0.1, random_state=42)
        model.fit(features)
        scores = model.decision_function(features)
        anomaly_ratio = float(np.mean(scores < 0))
        return min(anomaly_ratio * 100.0, 100.0)

    async def _over_provisioning_score(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> float:
        from backend.models.application import UserEntitlement
        result = await self.db.execute(
            select(func.count(UserEntitlement.id)).where(
                UserEntitlement.tenant_id == tenant_id,
                UserEntitlement.user_id == user_id,
                UserEntitlement.is_active == True,
            )
        )
        count = result.scalar() or 0
        if count <= 5:
            return 0.0
        if count <= 15:
            return 30.0
        if count <= 30:
            return 60.0
        return 90.0

    async def _cert_failure_score(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> float:
        result = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                CertificationItem.tenant_id == tenant_id,
                CertificationItem.user_id == user_id,
                CertificationItem.decision == "revoke",
            )
        )
        revoked = result.scalar() or 0
        result2 = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                CertificationItem.tenant_id == tenant_id,
                CertificationItem.user_id == user_id,
                CertificationItem.decision.in_(["certify", "revoke"]),
            )
        )
        total = result2.scalar() or 0
        if total == 0:
            return 0.0
        return min((revoked / total) * 100.0, 100.0)

    async def _peer_deviation_score(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> float:
        from backend.models.application import UserEntitlement
        from backend.models.user import User

        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user or not user.department_id:
            return 0.0

        peer_counts_result = await self.db.execute(
            select(func.count(UserEntitlement.id)).where(
                UserEntitlement.tenant_id == tenant_id,
                UserEntitlement.is_active == True,
            ).join(User, User.id == UserEntitlement.user_id).where(
                User.department_id == user.department_id,
            )
        )
        peer_result = await self.db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.department_id == user.department_id,
                User.is_active == True,
            )
        )
        total_peers = peer_result.scalar() or 1
        total_ents = peer_counts_result.scalar() or 0
        avg_per_peer = total_ents / total_peers if total_peers > 0 else 0

        user_ent_result = await self.db.execute(
            select(func.count(UserEntitlement.id)).where(
                UserEntitlement.tenant_id == tenant_id,
                UserEntitlement.user_id == user_id,
                UserEntitlement.is_active == True,
            )
        )
        user_count = user_ent_result.scalar() or 0

        if avg_per_peer == 0:
            return 0.0
        deviation = (user_count - avg_per_peer) / avg_per_peer
        if deviation <= 0:
            return 0.0
        return min(deviation * 50.0, 100.0)
