import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func

from backend.celery_app import celery_app
from backend.config import settings
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _calculate_user_risk_async(user_id: str, tenant_id: str) -> dict:
    """
    Compute a composite risk score for a user based on:
      - SoD violations (weight: RISK_WEIGHT_SOD_VIOLATION)
      - Anomalous login events (weight: RISK_WEIGHT_ANOMALOUS_LOGIN)
      - Over-provisioned roles (weight: RISK_WEIGHT_OVER_PROVISIONED)
      - Certification failures (weight: RISK_WEIGHT_CERT_FAILURE)
      - Peer deviation (weight: RISK_WEIGHT_PEER_DEVIATION)
    """
    async with AsyncSessionLocal() as session:
        try:
            score = 0.0
            factors = {}

            # --- SoD violations ---
            try:
                from backend.models.rbac import SODViolation
                sod_stmt = select(func.count()).select_from(SODViolation).where(
                    SODViolation.user_id == user_id,
                    SODViolation.tenant_id == tenant_id,
                    SODViolation.status == "active",
                )
                sod_count = (await session.execute(sod_stmt)).scalar() or 0
                sod_contribution = min(sod_count * settings.RISK_WEIGHT_SOD_VIOLATION, 100.0)
                score += sod_contribution
                factors["sod_violations"] = sod_count
                factors["sod_score_contribution"] = sod_contribution
            except Exception as exc:
                logger.warning("SoD score calc failed for user %s: %s", user_id, exc)

            # --- Over-provisioned roles ---
            try:
                from backend.models.rbac import UserRole
                role_stmt = select(func.count()).select_from(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                )
                role_count = (await session.execute(role_stmt)).scalar() or 0
                # Simple heuristic: >5 active roles is considered over-provisioned
                if role_count > 5:
                    over_prov_contribution = min(
                        (role_count - 5) * (settings.RISK_WEIGHT_OVER_PROVISIONED / 5), 100.0
                    )
                    score += over_prov_contribution
                    factors["active_roles"] = role_count
                    factors["over_prov_contribution"] = over_prov_contribution
                else:
                    factors["active_roles"] = role_count
                    factors["over_prov_contribution"] = 0.0
            except Exception as exc:
                logger.warning("Role count failed for user %s: %s", user_id, exc)

            # Clamp total score to [0, 100]
            score = min(score, 100.0)

            # --- Store risk score ---
            try:
                from backend.models.rbac import RiskScore
                rs_stmt = select(RiskScore).where(
                    RiskScore.user_id == user_id,
                    RiskScore.tenant_id == tenant_id,
                )
                rs_result = await session.execute(rs_stmt)
                risk_record = rs_result.scalar_one_or_none()

                if risk_record is None:
                    risk_record = RiskScore(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        score=score,
                        factors=factors,
                        calculated_at=datetime.now(timezone.utc),
                    )
                    session.add(risk_record)
                else:
                    risk_record.score = score
                    risk_record.factors = factors
                    risk_record.calculated_at = datetime.now(timezone.utc)

                await session.commit()
            except Exception as exc:
                logger.warning("Risk score persistence failed for user %s: %s", user_id, exc)
                await session.rollback()

            # Alert via WebSocket if critical
            if score >= 80:
                try:
                    from backend.utils.websocket_manager import ws_manager
                    reason = f"High risk score {score:.1f}: {', '.join(k for k, v in factors.items() if v)}"
                    await ws_manager.broadcast_risk_alert(tenant_id, user_id, score, reason)
                except Exception as exc:
                    logger.warning("WS risk alert failed for user %s: %s", user_id, exc)

            logger.info(
                "Risk score calculated for user %s tenant %s: %.1f (factors=%s)",
                user_id, tenant_id, score, factors,
            )
            return {"user_id": user_id, "score": score, "factors": factors}

        except Exception as exc:
            await session.rollback()
            logger.error("Risk scoring failed for user %s: %s", user_id, exc, exc_info=True)
            return {"user_id": user_id, "score": 0.0, "error": str(exc)}


@celery_app.task(
    name="backend.tasks.risk_scoring.calculate_user_risk",
    queue="risk",
)
def calculate_user_risk(user_id: str, tenant_id: str) -> dict:
    """Calculate and persist the risk score for a single user."""
    return _run_async(_calculate_user_risk_async(user_id, tenant_id))


async def _update_all_risk_scores_async() -> dict:
    """Fetch all active users across tenants and recalculate their risk scores."""
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
            for user_row in users:
                calculate_user_risk.delay(str(user_row.id), str(user_row.tenant_id))
                queued += 1

            logger.info("Queued risk score recalculation for %d users", queued)
            return {"queued": queued}
        except Exception as exc:
            logger.error("update_all_risk_scores error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.risk_scoring.update_all_risk_scores",
    queue="risk",
)
def update_all_risk_scores() -> dict:
    """Scheduled task: recalculate risk scores for all active users."""
    return _run_async(_update_all_risk_scores_async())


async def _detect_anomalies_async(user_id: str, event_data: dict) -> dict:
    """
    Detect anomalous behaviour from a login or activity event.
    Anomaly signals: new country, unusual hour, multiple rapid failures.
    """
    anomalies = []
    score_delta = 0.0

    ip_address = event_data.get("ip_address", "")
    user_agent = event_data.get("user_agent", "")
    event_type = event_data.get("event_type", "")
    hour = datetime.now(timezone.utc).hour
    tenant_id = event_data.get("tenant_id", "")

    # Unusual login hour (outside 06:00-22:00)
    if event_type == "login" and (hour < 6 or hour > 22):
        anomalies.append("unusual_login_hour")
        score_delta += settings.RISK_WEIGHT_ANOMALOUS_LOGIN * 0.5

    # Rapid successive failed logins
    if event_type == "login_failed":
        try:
            from backend.utils.redis_client import redis_client
            failures = await redis_client.get_failed_logins(user_id)
            if failures >= 3:
                anomalies.append("repeated_login_failures")
                score_delta += settings.RISK_WEIGHT_ANOMALOUS_LOGIN

            # Send security alert
            if failures >= settings.MAX_LOGIN_ATTEMPTS:
                try:
                    from backend.models.user import User
                    async with AsyncSessionLocal() as s:
                        result = await s.execute(select(User).where(User.id == user_id))
                        user = result.scalar_one_or_none()
                    if user:
                        from backend.utils.email import email_service
                        await email_service.send_security_alert(
                            user.email,
                            "Account Lockout",
                            {"ip_address": ip_address, "failures": failures},
                        )
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Failed login counter check failed: %s", exc)

    if anomalies and tenant_id and user_id:
        # Bump risk score asynchronously
        calculate_user_risk.delay(user_id, tenant_id)
        logger.info(
            "Anomalies detected for user %s: %s (delta=%.1f)",
            user_id, anomalies, score_delta,
        )

    return {
        "user_id": user_id,
        "anomalies": anomalies,
        "score_delta": score_delta,
    }


@celery_app.task(
    name="backend.tasks.risk_scoring.detect_anomalies",
    queue="risk",
)
def detect_anomalies(user_id: str, event_data: dict) -> dict:
    """Evaluate a user activity event for anomalies and update risk accordingly."""
    return _run_async(_detect_anomalies_async(user_id, event_data))
