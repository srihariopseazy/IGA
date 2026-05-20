import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_

from backend.celery_app import celery_app
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _scan_user_sod_async(user_id: str, tenant_id: str) -> dict:
    """
    Check a user's active role assignments against all active SoD rules.
    Creates or updates SODViolation records for conflicts found.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.rbac import UserRole, SODRule, SODViolation

            # Load active role IDs for this user
            role_stmt = select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                )
            )
            role_result = await session.execute(role_stmt)
            active_role_ids = {str(r) for r in role_result.scalars().all()}

            if not active_role_ids:
                return {"user_id": user_id, "violations": 0, "checked_rules": 0}

            # Load active SoD rules for this tenant
            rule_stmt = select(SODRule).where(
                and_(
                    SODRule.tenant_id == tenant_id,
                    SODRule.is_active == True,
                )
            )
            rule_result = await session.execute(rule_stmt)
            rules = rule_result.scalars().all()

            violations_found = 0
            violations_cleared = 0

            for rule in rules:
                role_a_id = str(getattr(rule, "role_a_id", ""))
                role_b_id = str(getattr(rule, "role_b_id", ""))

                has_a = role_a_id in active_role_ids
                has_b = role_b_id in active_role_ids
                is_conflict = has_a and has_b

                # Check for existing violation record
                viol_stmt = select(SODViolation).where(
                    and_(
                        SODViolation.user_id == user_id,
                        SODViolation.rule_id == str(rule.id),
                        SODViolation.tenant_id == tenant_id,
                    )
                )
                viol_result = await session.execute(viol_stmt)
                existing_violation = viol_result.scalar_one_or_none()

                if is_conflict:
                    if existing_violation is None:
                        new_violation = SODViolation(
                            user_id=user_id,
                            rule_id=str(rule.id),
                            tenant_id=tenant_id,
                            role_a_id=role_a_id,
                            role_b_id=role_b_id,
                            status="active",
                            severity=getattr(rule, "severity", "high"),
                            detected_at=datetime.now(timezone.utc),
                        )
                        session.add(new_violation)
                        violations_found += 1
                        logger.warning(
                            "SoD violation detected: user=%s rule=%s roles=(%s, %s)",
                            user_id, rule.id, role_a_id, role_b_id,
                        )

                        # Send critical alert via WebSocket if severity is critical
                        if getattr(rule, "severity", "high") == "critical":
                            try:
                                from backend.utils.websocket_manager import ws_manager
                                await ws_manager.broadcast_risk_alert(
                                    tenant_id,
                                    user_id,
                                    95.0,
                                    f"Critical SoD violation: rule {rule.id}",
                                )
                            except Exception:
                                pass
                    else:
                        # Update detection time
                        existing_violation.detected_at = datetime.now(timezone.utc)
                        existing_violation.status = "active"
                else:
                    # Conflict resolved - mark violation as cleared
                    if existing_violation and existing_violation.status == "active":
                        existing_violation.status = "resolved"
                        existing_violation.resolved_at = datetime.now(timezone.utc)
                        violations_cleared += 1

            await session.commit()

            logger.info(
                "SoD scan complete for user %s: %d rules checked, %d violations found, %d cleared",
                user_id, len(rules), violations_found, violations_cleared,
            )
            return {
                "user_id": user_id,
                "checked_rules": len(rules),
                "active_roles": len(active_role_ids),
                "violations_found": violations_found,
                "violations_cleared": violations_cleared,
            }

        except Exception as exc:
            await session.rollback()
            logger.error("SoD scan failed for user %s: %s", user_id, exc, exc_info=True)
            return {"user_id": user_id, "error": str(exc)}


@celery_app.task(
    name="backend.tasks.sod_scan.scan_user",
    queue="sod",
)
def scan_user_sod(user_id: str, tenant_id: str) -> dict:
    """Scan a single user for SoD violations."""
    return _run_async(_scan_user_sod_async(user_id, tenant_id))


async def _scan_all_tenants_async() -> dict:
    """Iterate all active users across all tenants and queue SoD scans."""
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.user import User
            stmt = select(User.id, User.tenant_id).where(
                User.is_active == True,
                User.deleted_at == None,
            )
            result = await session.execute(stmt)
            users = result.all()

            queued = 0
            for row in users:
                scan_user_sod.delay(str(row.id), str(row.tenant_id))
                queued += 1

            logger.info("Queued SoD scans for %d users", queued)
            return {"queued": queued}
        except Exception as exc:
            logger.error("scan_all_tenants error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.sod_scan.scan_all_tenants",
    queue="sod",
)
def scan_all_tenants() -> dict:
    """Scheduled task: scan all active users in all tenants for SoD violations."""
    return _run_async(_scan_all_tenants_async())


async def _simulate_sod_conflict_async(
    user_id: str, new_role_id: str, tenant_id: str
) -> dict:
    """
    Simulate adding a role to a user and return any SoD conflicts
    WITHOUT persisting any changes to the database.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.rbac import UserRole, SODRule

            # Current active roles
            role_stmt = select(UserRole.role_id).where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                )
            )
            role_result = await session.execute(role_stmt)
            current_role_ids = {str(r) for r in role_result.scalars().all()}
            simulated_role_ids = current_role_ids | {new_role_id}

            # Load rules
            rule_stmt = select(SODRule).where(
                and_(
                    SODRule.tenant_id == tenant_id,
                    SODRule.is_active == True,
                )
            )
            rule_result = await session.execute(rule_stmt)
            rules = rule_result.scalars().all()

            conflicts = []
            for rule in rules:
                role_a_id = str(getattr(rule, "role_a_id", ""))
                role_b_id = str(getattr(rule, "role_b_id", ""))
                if role_a_id in simulated_role_ids and role_b_id in simulated_role_ids:
                    conflicts.append({
                        "rule_id": str(rule.id),
                        "rule_name": getattr(rule, "name", ""),
                        "severity": getattr(rule, "severity", "high"),
                        "role_a_id": role_a_id,
                        "role_b_id": role_b_id,
                    })

            return {
                "user_id": user_id,
                "new_role_id": new_role_id,
                "would_create_conflict": len(conflicts) > 0,
                "conflicts": conflicts,
            }
        except Exception as exc:
            logger.error(
                "SoD simulation failed for user %s role %s: %s",
                user_id, new_role_id, exc,
            )
            return {"error": str(exc), "would_create_conflict": False, "conflicts": []}


@celery_app.task(
    name="backend.tasks.sod_scan.simulate_sod_conflict",
    queue="sod",
)
def simulate_sod_conflict(user_id: str, new_role_id: str, tenant_id: str) -> dict:
    """Simulate adding a role and return any SoD conflicts (read-only, no DB writes)."""
    return _run_async(_simulate_sod_conflict_async(user_id, new_role_id, tenant_id))
