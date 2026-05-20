from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from backend.models.risk import (
    AccessRecommendation,
    IdentityRiskHistory,
    RiskScore,
    UserBehaviorEvent,
)
from backend.models.user import User

logger = logging.getLogger(__name__)


def _risk_level_from_score(score: float) -> str:
    if score >= 80:
        return "critical"
    elif score >= 60:
        return "high"
    elif score >= 40:
        return "medium"
    return "low"


class RiskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_user_risk(self, user_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Compute composite risk score with all 5 components:
        - SoD violations (30%)
        - Anomalous behavior (20%)
        - Over-provisioning (15%)
        - Certification failures (20%)
        - Peer deviation (15%)
        """
        from backend.config import settings

        sod_score = await self._calc_sod_score(user_id, tenant_id)
        anomaly_score = await self._calc_anomaly_score(user_id, tenant_id)
        over_prov_score = await self._calc_over_provisioning_score(user_id, tenant_id)
        cert_score = await self._calc_cert_failure_score(user_id, tenant_id)
        peer_score = await self._calc_peer_deviation_score(user_id, tenant_id)

        w_sod = settings.RISK_WEIGHT_SOD_VIOLATION / 100
        w_anomaly = settings.RISK_WEIGHT_ANOMALOUS_LOGIN / 100
        w_over = settings.RISK_WEIGHT_OVER_PROVISIONED / 100
        w_cert = settings.RISK_WEIGHT_CERT_FAILURE / 100
        w_peer = settings.RISK_WEIGHT_PEER_DEVIATION / 100

        overall = (
            sod_score * w_sod
            + anomaly_score * w_anomaly
            + over_prov_score * w_over
            + cert_score * w_cert
            + peer_score * w_peer
        )
        overall = round(min(100.0, max(0.0, overall)), 2)
        risk_level = _risk_level_from_score(overall)

        return {
            "user_id": user_id,
            "overall_score": overall,
            "risk_level": risk_level,
            "components": {
                "sod_violations": round(sod_score, 2),
                "anomalous_behavior": round(anomaly_score, 2),
                "over_provisioning": round(over_prov_score, 2),
                "cert_failures": round(cert_score, 2),
                "peer_deviation": round(peer_score, 2),
            },
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _calc_sod_score(self, user_id: str, tenant_id: str) -> float:
        """Score based on open SoD violations (0-100)."""
        from backend.models.sod import SODViolation

        result = await self.db.execute(
            select(func.count(SODViolation.id)).where(
                and_(
                    SODViolation.user_id == user_id,
                    SODViolation.tenant_id == tenant_id,
                    SODViolation.status == "open",
                )
            )
        )
        count = result.scalar() or 0
        # Each open violation adds 25 points, capped at 100
        return min(100.0, count * 25.0)

    async def _calc_anomaly_score(self, user_id: str, tenant_id: str) -> float:
        """Score based on recent anomalous behavior events (0-100)."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        result = await self.db.execute(
            select(func.avg(UserBehaviorEvent.anomaly_score)).where(
                and_(
                    UserBehaviorEvent.user_id == user_id,
                    UserBehaviorEvent.tenant_id == tenant_id,
                    UserBehaviorEvent.is_anomalous == True,  # noqa: E712
                    UserBehaviorEvent.created_at >= since,
                )
            )
        )
        avg = result.scalar()
        if avg is None:
            # Check if there are any anomalous events at all
            count_result = await self.db.execute(
                select(func.count(UserBehaviorEvent.id)).where(
                    and_(
                        UserBehaviorEvent.user_id == user_id,
                        UserBehaviorEvent.is_anomalous == True,  # noqa: E712
                    )
                )
            )
            if (count_result.scalar() or 0) == 0:
                return 0.0
        return float(avg or 0.0)

    async def _calc_over_provisioning_score(self, user_id: str, tenant_id: str) -> float:
        """
        Score based on number of roles vs peer average.
        If user has significantly more roles than peers, score is higher.
        """
        from backend.models.rbac import UserRole

        user_roles_result = await self.db.execute(
            select(func.count(UserRole.id)).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_role_count = user_roles_result.scalar() or 0

        # Get tenant average role count
        avg_result = await self.db.execute(
            select(func.avg(func.count(UserRole.id)))
            .where(
                and_(
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
            .group_by(UserRole.user_id)
        )
        avg_roles = avg_result.scalar()

        if not avg_roles or avg_roles == 0:
            return 0.0

        ratio = user_role_count / float(avg_roles)
        if ratio <= 1.0:
            return 0.0
        elif ratio <= 1.5:
            return 20.0
        elif ratio <= 2.0:
            return 40.0
        elif ratio <= 3.0:
            return 65.0
        else:
            return 90.0

    async def _calc_cert_failure_score(self, user_id: str, tenant_id: str) -> float:
        """Score based on certification revocations and pending items (0-100)."""
        from backend.models.certification import CertificationItem

        # Recent revocations in last 180 days
        since = datetime.now(timezone.utc) - timedelta(days=180)
        revoked_result = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                and_(
                    CertificationItem.user_id == user_id,
                    CertificationItem.tenant_id == tenant_id,
                    CertificationItem.status == "revoked",
                    CertificationItem.decided_at >= since,
                )
            )
        )
        revoked = revoked_result.scalar() or 0

        # Overdue pending items
        pending_result = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                and_(
                    CertificationItem.user_id == user_id,
                    CertificationItem.tenant_id == tenant_id,
                    CertificationItem.status == "pending",
                )
            )
        )
        pending = pending_result.scalar() or 0

        return min(100.0, revoked * 30.0 + pending * 5.0)

    async def _calc_peer_deviation_score(self, user_id: str, tenant_id: str) -> float:
        """
        Score based on deviation from peer role profile.
        Uses department/job-title peers as comparison group.
        """
        from backend.models.rbac import UserRole
        from backend.models.user import UserProfile

        # Get user's department
        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile or not profile.department:
            return 0.0

        # Get user's roles
        user_roles_result = await self.db.execute(
            select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_role_ids = set(str(r[0]) for r in user_roles_result.all())

        # Get peer users (same department)
        peer_profiles_result = await self.db.execute(
            select(UserProfile.user_id).where(
                and_(
                    UserProfile.department == profile.department,
                    UserProfile.user_id != user_id,
                )
            )
        )
        peer_ids = [str(r[0]) for r in peer_profiles_result.all()]

        if not peer_ids:
            return 0.0

        # Get peer role distribution
        peer_roles_result = await self.db.execute(
            select(UserRole.role_id, func.count(UserRole.user_id).label("peer_count"))
            .where(
                and_(
                    UserRole.user_id.in_(peer_ids),
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
            .group_by(UserRole.role_id)
        )
        peer_role_counts = {str(r[0]): r[1] for r in peer_roles_result.all()}
        total_peers = len(peer_ids)

        if not peer_role_counts:
            return 0.0

        # Common peer roles (>50% of peers have it)
        common_peer_roles = {
            rid
            for rid, cnt in peer_role_counts.items()
            if cnt / total_peers >= 0.5
        }

        # Roles user has that peers don't (unusual roles)
        unusual_roles = user_role_ids - common_peer_roles
        # Common peer roles user is missing
        missing_common = common_peer_roles - user_role_ids

        deviation_count = len(unusual_roles) + len(missing_common)
        return min(100.0, deviation_count * 15.0)

    async def detect_anomaly(
        self,
        user_id: str,
        event_data: Dict[str, Any],
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if an event is anomalous. Returns anomaly details or None.
        Basic heuristics: unusual IP country, off-hours login, impossible travel.
        """
        anomaly_score = 0.0
        reasons = []

        event_type = event_data.get("event_type", "")
        country = event_data.get("country")
        ip = event_data.get("ip_address")
        event_time = event_data.get("timestamp", datetime.now(timezone.utc))
        if isinstance(event_time, str):
            try:
                event_time = datetime.fromisoformat(event_time)
            except Exception:
                event_time = datetime.now(timezone.utc)

        # Check for new country
        if country:
            past_countries_result = await self.db.execute(
                select(UserBehaviorEvent.country)
                .where(
                    and_(
                        UserBehaviorEvent.user_id == user_id,
                        UserBehaviorEvent.country.isnot(None),
                    )
                )
                .distinct()
            )
            known_countries = {r[0] for r in past_countries_result.all()}
            if known_countries and country not in known_countries:
                anomaly_score += 40.0
                reasons.append(f"Login from new country: {country}")

        # Off-hours login (UTC hours 0-6)
        hour = event_time.hour if hasattr(event_time, "hour") else 12
        if hour < 6:
            anomaly_score += 20.0
            reasons.append(f"Off-hours activity at {hour:02d}:00 UTC")

        # Rapid successive logins from different IPs
        if event_type in ("login", "auth"):
            recent_events_result = await self.db.execute(
                select(UserBehaviorEvent)
                .where(
                    and_(
                        UserBehaviorEvent.user_id == user_id,
                        UserBehaviorEvent.event_type == event_type,
                        UserBehaviorEvent.created_at
                        >= datetime.now(timezone.utc) - timedelta(minutes=10),
                    )
                )
                .limit(5)
            )
            recent = recent_events_result.scalars().all()
            unique_ips = {e.ip_address for e in recent if e.ip_address} | ({ip} if ip else set())
            if len(unique_ips) >= 3:
                anomaly_score += 50.0
                reasons.append("Logins from multiple IPs within 10 minutes")

        is_anomalous = anomaly_score >= 30.0

        # Record the behavior event
        behavior_event = UserBehaviorEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            event_type=event_type,
            resource_type=event_data.get("resource_type"),
            ip_address=ip,
            country=country,
            anomaly_score=anomaly_score,
            is_anomalous=is_anomalous,
            metadata={
                "reasons": reasons,
                "raw_data": {k: v for k, v in event_data.items() if k != "password"},
            },
        )
        self.db.add(behavior_event)
        await self.db.commit()

        if is_anomalous:
            return {
                "anomaly_score": anomaly_score,
                "is_anomalous": True,
                "reasons": reasons,
                "event_id": str(behavior_event.id),
            }
        return None

    async def get_access_recommendations(
        self, user_id: str, tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Generate access recommendations for a user based on peer analysis."""
        from backend.models.rbac import UserRole, Role
        from backend.models.user import UserProfile

        # Get user's current roles
        user_roles_result = await self.db.execute(
            select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        user_role_ids = set(str(r[0]) for r in user_roles_result.all())

        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile or not profile.department:
            return []

        # Peer analysis
        peer_profiles_result = await self.db.execute(
            select(UserProfile.user_id).where(
                and_(
                    UserProfile.department == profile.department,
                    UserProfile.user_id != user_id,
                )
            )
        )
        peer_ids = [str(r[0]) for r in peer_profiles_result.all()]
        if not peer_ids:
            return []

        total_peers = len(peer_ids)
        peer_roles_result = await self.db.execute(
            select(UserRole.role_id, func.count(UserRole.user_id).label("cnt"))
            .where(
                and_(
                    UserRole.user_id.in_(peer_ids),
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
            .group_by(UserRole.role_id)
        )
        peer_role_counts = {str(r[0]): r[1] for r in peer_roles_result.all()}

        recommendations = []

        for role_id_str, count in peer_role_counts.items():
            peer_pct = count / total_peers
            if role_id_str not in user_role_ids and peer_pct >= 0.7:
                # 70%+ of peers have this role; recommend granting
                recommendations.append(
                    {
                        "type": "grant",
                        "item_type": "role",
                        "item_id": role_id_str,
                        "confidence_score": round(peer_pct * 100, 1),
                        "reason": f"{int(peer_pct*100)}% of peers in {profile.department} have this role",
                        "peer_count": count,
                        "total_peers": total_peers,
                    }
                )

        # Roles user has that almost no peers have (potential revoke)
        for role_id_str in user_role_ids:
            peer_pct = peer_role_counts.get(role_id_str, 0) / total_peers
            if peer_pct < 0.1:
                recommendations.append(
                    {
                        "type": "revoke",
                        "item_type": "role",
                        "item_id": role_id_str,
                        "confidence_score": round((1 - peer_pct) * 100, 1),
                        "reason": f"Only {int(peer_pct*100)}% of peers in {profile.department} have this role",
                        "peer_count": peer_role_counts.get(role_id_str, 0),
                        "total_peers": total_peers,
                    }
                )

        return recommendations

    async def get_risk_heatmap(self, tenant_id: str) -> Dict[str, Any]:
        """Return aggregated risk data by department."""
        from backend.models.rbac import Department
        from backend.models.user import User as UserModel

        rows = await self.db.execute(
            select(
                UserModel.department_id,
                func.avg(RiskScore.overall_score).label("avg_score"),
                func.max(RiskScore.overall_score).label("max_score"),
                func.count(RiskScore.id).label("user_count"),
            )
            .join(RiskScore, RiskScore.user_id == UserModel.id)
            .where(
                and_(
                    RiskScore.tenant_id == tenant_id,
                    UserModel.tenant_id == tenant_id,
                    UserModel.deleted_at.is_(None),
                )
            )
            .group_by(UserModel.department_id)
        )
        dept_data = rows.all()

        dept_ids = [r[0] for r in dept_data if r[0]]
        dept_names: Dict[str, str] = {}
        if dept_ids:
            dept_result = await self.db.execute(
                select(Department.id, Department.name).where(Department.id.in_(dept_ids))
            )
            dept_names = {str(r[0]): r[1] for r in dept_result.all()}

        heatmap = []
        for row in dept_data:
            dept_id = str(row[0]) if row[0] else "unassigned"
            heatmap.append(
                {
                    "department_id": dept_id,
                    "department_name": dept_names.get(dept_id, "Unassigned"),
                    "avg_risk_score": round(float(row[1] or 0), 1),
                    "max_risk_score": round(float(row[2] or 0), 1),
                    "user_count": row[3],
                    "risk_level": _risk_level_from_score(float(row[1] or 0)),
                }
            )

        heatmap.sort(key=lambda x: x["avg_risk_score"], reverse=True)
        return {
            "departments": heatmap,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def update_risk_score(
        self, user_id: str, tenant_id: str
    ) -> Optional[RiskScore]:
        """Calculate and persist the risk score for a user."""
        risk_data = await self.calculate_user_risk(user_id, tenant_id)

        result = await self.db.execute(
            select(RiskScore).where(
                and_(
                    RiskScore.user_id == user_id,
                    RiskScore.tenant_id == tenant_id,
                )
            )
        )
        score_record = result.scalar_one_or_none()

        components = risk_data["components"]

        if score_record:
            score_record.overall_score = risk_data["overall_score"]
            score_record.risk_level = risk_data["risk_level"]
            score_record.sod_score = components["sod_violations"]
            score_record.anomaly_score = components["anomalous_behavior"]
            score_record.over_provisioning_score = components["over_provisioning"]
            score_record.cert_failure_score = components["cert_failures"]
            score_record.peer_deviation_score = components["peer_deviation"]
            score_record.last_calculated_at = datetime.now(timezone.utc)
            score_record.factors = components
        else:
            score_record = RiskScore(
                user_id=user_id,
                tenant_id=tenant_id,
                overall_score=risk_data["overall_score"],
                risk_level=risk_data["risk_level"],
                sod_score=components["sod_violations"],
                anomaly_score=components["anomalous_behavior"],
                over_provisioning_score=components["over_provisioning"],
                cert_failure_score=components["cert_failures"],
                peer_deviation_score=components["peer_deviation"],
                last_calculated_at=datetime.now(timezone.utc),
                factors=components,
            )
            self.db.add(score_record)

        # Also record history snapshot
        history = IdentityRiskHistory(
            user_id=user_id,
            tenant_id=tenant_id,
            overall_score=risk_data["overall_score"],
            risk_level=risk_data["risk_level"],
            snapshot_date=datetime.now(timezone.utc),
            factors=components,
        )
        self.db.add(history)

        await self.db.commit()
        await self.db.refresh(score_record)
        return score_record
