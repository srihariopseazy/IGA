from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Dict, Optional
from datetime import datetime, timezone
import logging

from backend.models.sod import SODPolicy, SODRule, SODViolation
from backend.models.rbac import UserRole, Role

logger = logging.getLogger(__name__)


class SODService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_access_request_for_conflicts(
        self,
        user_id: str,
        requested_role_ids: List[str],
        tenant_id: str,
    ) -> List[dict]:
        """Check if granting these roles would cause SoD violations."""
        current_result = await self.db.execute(
            select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        current_ids = [str(r[0]) for r in current_result.all()]
        all_ids = list(set(current_ids + [str(r) for r in requested_role_ids]))

        rules_result = await self.db.execute(
            select(SODRule).where(
                and_(
                    SODRule.tenant_id == tenant_id,
                    SODRule.deleted_at.is_(None),
                )
            )
        )
        rules = rules_result.scalars().all()

        conflicts = []
        for rule in rules:
            r1, r2 = str(rule.role_id_1), str(rule.role_id_2)
            if r1 in all_ids and r2 in all_ids:
                conflicts.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "role_id_1": r1,
                        "role_id_2": r2,
                        "conflict_type": rule.conflict_type,
                        "description": rule.description,
                        "policy_id": str(rule.policy_id),
                    }
                )
        return conflicts

    async def scan_user(self, user_id: str, tenant_id: str) -> List[SODViolation]:
        """Scan user for current SoD violations. Creates new violations and resolves stale ones."""
        current_result = await self.db.execute(
            select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.deleted_at.is_(None),
                )
            )
        )
        current_ids = [str(r[0]) for r in current_result.all()]

        rules_result = await self.db.execute(
            select(SODRule).where(
                and_(
                    SODRule.tenant_id == tenant_id,
                    SODRule.deleted_at.is_(None),
                )
            )
        )
        rules = rules_result.scalars().all()

        existing_result = await self.db.execute(
            select(SODViolation).where(
                and_(
                    SODViolation.user_id == user_id,
                    SODViolation.tenant_id == tenant_id,
                    SODViolation.status == "open",
                )
            )
        )
        existing = {
            (str(v.role_id_1), str(v.role_id_2)): v
            for v in existing_result.scalars().all()
        }

        new_violations: List[SODViolation] = []
        active_pairs: set = set()

        for rule in rules:
            r1, r2 = str(rule.role_id_1), str(rule.role_id_2)
            if r1 in current_ids and r2 in current_ids:
                active_pairs.add((r1, r2))
                key = (r1, r2)
                if key not in existing:
                    v = SODViolation(
                        tenant_id=tenant_id,
                        sod_rule_id=rule.id,
                        user_id=user_id,
                        role_id_1=rule.role_id_1,
                        role_id_2=rule.role_id_2,
                        detection_date=datetime.now(timezone.utc),
                        status="open",
                        risk_score=75.0,
                    )
                    self.db.add(v)
                    new_violations.append(v)
                    logger.info(
                        "New SoD violation for user %s rule %s",
                        user_id,
                        str(rule.id),
                    )

        # Resolve violations that no longer apply (roles removed)
        for (r1, r2), v in existing.items():
            if (r1, r2) not in active_pairs:
                v.status = "resolved"
                logger.info(
                    "Resolved SoD violation %s for user %s (roles removed)",
                    str(v.id),
                    user_id,
                )

        await self.db.commit()
        return new_violations

    async def scan_all_users(self, tenant_id: str) -> dict:
        """Scan all active users in tenant for SoD violations."""
        from backend.models.user import User

        users_result = await self.db.execute(
            select(User.id).where(
                and_(
                    User.tenant_id == tenant_id,
                    User.status == "active",
                    User.deleted_at.is_(None),
                )
            )
        )
        user_ids = [str(r[0]) for r in users_result.all()]
        total_violations = 0
        errors = 0

        for uid in user_ids:
            try:
                violations = await self.scan_user(uid, tenant_id)
                total_violations += len(violations)
            except Exception as e:
                logger.error("Error scanning user %s: %s", uid, e)
                errors += 1

        return {
            "users_scanned": len(user_ids),
            "new_violations": total_violations,
            "errors": errors,
        }

    async def get_sod_stats(self, tenant_id: str) -> dict:
        total = (
            await self.db.execute(
                select(func.count(SODViolation.id)).where(
                    SODViolation.tenant_id == tenant_id
                )
            )
        ).scalar() or 0

        open_count = (
            await self.db.execute(
                select(func.count(SODViolation.id)).where(
                    and_(
                        SODViolation.tenant_id == tenant_id,
                        SODViolation.status == "open",
                    )
                )
            )
        ).scalar() or 0

        mitigated = (
            await self.db.execute(
                select(func.count(SODViolation.id)).where(
                    and_(
                        SODViolation.tenant_id == tenant_id,
                        SODViolation.status == "mitigated",
                    )
                )
            )
        ).scalar() or 0

        critical = (
            await self.db.execute(
                select(func.count(SODViolation.id)).where(
                    and_(
                        SODViolation.tenant_id == tenant_id,
                        SODViolation.status == "open",
                        SODViolation.risk_score >= 80,
                    )
                )
            )
        ).scalar() or 0

        policy_count = (
            await self.db.execute(
                select(func.count(SODPolicy.id)).where(
                    and_(
                        SODPolicy.tenant_id == tenant_id,
                        SODPolicy.deleted_at.is_(None),
                    )
                )
            )
        ).scalar() or 0

        rule_count = (
            await self.db.execute(
                select(func.count(SODRule.id)).where(
                    and_(
                        SODRule.tenant_id == tenant_id,
                        SODRule.deleted_at.is_(None),
                    )
                )
            )
        ).scalar() or 0

        return {
            "total": total,
            "open": open_count,
            "critical": critical,
            "mitigated": mitigated,
            "resolved": total - open_count - mitigated,
            "policies": policy_count,
            "rules": rule_count,
        }

    async def get_violations_for_user(
        self,
        user_id: str,
        tenant_id: str,
        violation_status: Optional[str] = None,
    ) -> List[SODViolation]:
        """Return all violations for a specific user."""
        query = select(SODViolation).where(
            and_(
                SODViolation.user_id == user_id,
                SODViolation.tenant_id == tenant_id,
            )
        )
        if violation_status:
            query = query.where(SODViolation.status == violation_status)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def mitigate_violation(
        self,
        violation_id: str,
        mitigated_by: str,
        mitigation_notes: str,
        new_status: str = "mitigated",
    ) -> Optional[SODViolation]:
        """Apply mitigation to a violation."""
        result = await self.db.execute(
            select(SODViolation).where(SODViolation.id == violation_id)
        )
        v = result.scalar_one_or_none()
        if not v:
            return None
        v.mitigation_notes = mitigation_notes
        v.status = new_status
        v.mitigated_by = mitigated_by
        v.mitigated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return v
