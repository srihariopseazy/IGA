import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_, update

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


async def _check_deadlines_async() -> dict:
    """
    Find certification campaigns near their deadline and:
    - Send reminder emails to reviewers with pending items
    - Escalate items that are past due
    - Auto-revoke access if the campaign is configured to do so
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import CertificationCampaign, CertificationItem

            now = datetime.now(timezone.utc)
            escalation_threshold = now + timedelta(days=settings.CERTIFICATION_ESCALATION_DAYS)

            # Find campaigns that are active and approaching deadline
            stmt = select(CertificationCampaign).where(
                and_(
                    CertificationCampaign.status == "active",
                    CertificationCampaign.deadline <= escalation_threshold,
                    CertificationCampaign.deadline >= now,
                )
            )
            result = await session.execute(stmt)
            campaigns = result.scalars().all()

            reminders_sent = 0
            escalations = 0

            for campaign in campaigns:
                tenant_id = str(campaign.tenant_id)
                campaign_id = str(campaign.id)
                days_remaining = (campaign.deadline - now).days

                # Find pending items
                items_stmt = select(CertificationItem).where(
                    and_(
                        CertificationItem.campaign_id == campaign_id,
                        CertificationItem.status == "pending",
                    )
                )
                items_result = await session.execute(items_stmt)
                pending_items = items_result.scalars().all()

                if not pending_items:
                    continue

                # Group by reviewer
                reviewer_items: dict = {}
                for item in pending_items:
                    reviewer_id = str(getattr(item, "reviewer_id", ""))
                    if reviewer_id:
                        reviewer_items.setdefault(reviewer_id, []).append(item)

                # Send reminder emails
                from backend.tasks.notification import send_certification_reminder_email
                for reviewer_id, items in reviewer_items.items():
                    try:
                        send_certification_reminder_email.delay(
                            reviewer_id=reviewer_id,
                            campaign_id=campaign_id,
                            tenant_id=tenant_id,
                            items_count=len(items),
                            days_remaining=days_remaining,
                        )
                        reminders_sent += 1
                    except Exception as exc:
                        logger.warning(
                            "Failed to queue reminder for reviewer %s: %s", reviewer_id, exc
                        )

                # Escalate overdue items (deadline already passed)
                overdue_stmt = select(CertificationItem).where(
                    and_(
                        CertificationItem.campaign_id == campaign_id,
                        CertificationItem.status == "pending",
                        CertificationItem.due_at < now,
                    )
                )
                overdue_result = await session.execute(overdue_stmt)
                overdue_items = overdue_result.scalars().all()

                for item in overdue_items:
                    item.status = "escalated"
                    item.escalated_at = now
                    escalations += 1

                    # Auto-revoke if campaign is configured for it
                    if getattr(campaign, "auto_revoke_on_no_action", False):
                        item.decision = "revoke"
                        item.decision_reason = "Auto-revoked: deadline exceeded"
                        item.decided_at = now
                        item.status = "decided"

            await session.commit()
            logger.info(
                "Certification deadline check: %d reminders sent, %d escalations",
                reminders_sent, escalations,
            )
            return {"reminders_sent": reminders_sent, "escalations": escalations}

        except Exception as exc:
            await session.rollback()
            logger.error("check_deadlines error: %s", exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.certification.check_deadlines",
    queue="certification",
)
def check_deadlines() -> dict:
    """Check certification campaign deadlines and send reminders/escalations."""
    return _run_async(_check_deadlines_async())


async def _generate_campaign_items_async(campaign_id: str, tenant_id: str) -> dict:
    """
    Generate CertificationItem records for an access review campaign.
    Scans all user-role/entitlement assignments within the campaign scope.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import CertificationCampaign, CertificationItem
            from backend.models.rbac import UserRole
            from backend.models.user import User

            stmt = select(CertificationCampaign).where(
                CertificationCampaign.id == campaign_id,
                CertificationCampaign.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            campaign = result.scalar_one_or_none()

            if campaign is None:
                logger.error("Campaign %s not found for tenant %s", campaign_id, tenant_id)
                return {"error": "campaign_not_found"}

            scope = getattr(campaign, "scope", {}) or {}
            scope_type = scope.get("type", "all_users")
            reviewer_id = str(getattr(campaign, "default_reviewer_id", ""))

            # Determine users in scope
            user_stmt = select(User).where(
                User.tenant_id == tenant_id,
                User.is_active == True,
                User.deleted_at == None,
            )
            if scope_type == "department" and scope.get("department_id"):
                user_stmt = user_stmt.where(User.department_id == scope["department_id"])

            user_result = await session.execute(user_stmt)
            users = user_result.scalars().all()

            items_created = 0
            for user in users:
                # Get user's active roles
                role_stmt = select(UserRole).where(
                    UserRole.user_id == str(user.id),
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                )
                role_result = await session.execute(role_stmt)
                user_roles = role_result.scalars().all()

                for ur in user_roles:
                    # Check if item already exists
                    existing_stmt = select(CertificationItem).where(
                        CertificationItem.campaign_id == campaign_id,
                        CertificationItem.user_id == str(user.id),
                        CertificationItem.item_type == "role",
                        CertificationItem.item_id == str(ur.role_id),
                    )
                    existing_result = await session.execute(existing_stmt)
                    if existing_result.scalar_one_or_none() is not None:
                        continue

                    item = CertificationItem(
                        campaign_id=campaign_id,
                        tenant_id=tenant_id,
                        user_id=str(user.id),
                        reviewer_id=reviewer_id if reviewer_id else str(user.id),
                        item_type="role",
                        item_id=str(ur.role_id),
                        status="pending",
                        due_at=campaign.deadline,
                    )
                    session.add(item)
                    items_created += 1

            # Update campaign status
            campaign.status = "active"
            campaign.items_count = items_created

            await session.commit()
            logger.info(
                "Generated %d items for campaign %s tenant %s",
                items_created, campaign_id, tenant_id,
            )
            return {"campaign_id": campaign_id, "items_created": items_created}

        except Exception as exc:
            await session.rollback()
            logger.error(
                "generate_campaign_items error for campaign %s: %s", campaign_id, exc, exc_info=True
            )
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.certification.generate_campaign_items",
    queue="certification",
)
def generate_campaign_items(campaign_id: str, tenant_id: str) -> dict:
    """Generate review items for a certification campaign."""
    return _run_async(_generate_campaign_items_async(campaign_id, tenant_id))


async def _export_results_async(campaign_id: str, tenant_id: str) -> str:
    """
    Export certification results as a CSV and upload to MinIO.
    Returns the presigned URL to the uploaded file.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import CertificationCampaign, CertificationItem

            stmt = select(CertificationItem).where(
                CertificationItem.campaign_id == campaign_id,
                CertificationItem.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            items = result.scalars().all()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "item_id", "user_id", "item_type", "item_id_ref",
                "reviewer_id", "status", "decision", "decision_reason",
                "decided_at", "created_at",
            ])
            for item in items:
                writer.writerow([
                    str(item.id),
                    str(getattr(item, "user_id", "")),
                    getattr(item, "item_type", ""),
                    str(getattr(item, "item_id", "")),
                    str(getattr(item, "reviewer_id", "")),
                    getattr(item, "status", ""),
                    getattr(item, "decision", ""),
                    getattr(item, "decision_reason", ""),
                    str(getattr(item, "decided_at", "")),
                    str(getattr(item, "created_at", "")),
                ])

            csv_bytes = output.getvalue().encode("utf-8")

            from backend.utils.minio_client import minio_client
            object_path = await minio_client.upload_audit_evidence(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                data=csv_bytes,
                filename=f"results_{campaign_id}.csv",
            )

            from datetime import timedelta
            url = await minio_client.get_presigned_url(
                bucket=settings.MINIO_BUCKET,
                object_name=object_path,
                expires=timedelta(hours=24),
            )
            logger.info("Campaign %s results exported: %s", campaign_id, url)
            return url

        except Exception as exc:
            logger.error(
                "export_results failed for campaign %s: %s", campaign_id, exc, exc_info=True
            )
            return ""


@celery_app.task(
    name="backend.tasks.certification.export_results",
    queue="certification",
)
def export_results(campaign_id: str, tenant_id: str) -> str:
    """Export certification campaign results to CSV and upload to MinIO."""
    return _run_async(_export_results_async(campaign_id, tenant_id))


@celery_app.task(
    name="backend.tasks.certification.send_certification_reminder_email",
    queue="notification",
)
def send_certification_reminder_email(
    reviewer_id: str,
    campaign_id: str,
    tenant_id: str,
    items_count: int,
    days_remaining: int,
) -> bool:
    async def _send():
        async with AsyncSessionLocal() as session:
            from backend.models.user import User
            from backend.models.application import CertificationCampaign
            user_result = await session.execute(select(User).where(User.id == reviewer_id))
            user = user_result.scalar_one_or_none()
            camp_result = await session.execute(
                select(CertificationCampaign).where(CertificationCampaign.id == campaign_id)
            )
            campaign = camp_result.scalar_one_or_none()
            if user and campaign:
                from backend.utils.email import email_service
                deadline_str = campaign.deadline.strftime("%Y-%m-%d") if campaign.deadline else "N/A"
                review_link = f"{settings.FRONTEND_URL}/certifications/{campaign_id}/review"
                await email_service.send_certification_reminder(
                    reviewer_email=user.email,
                    campaign_name=getattr(campaign, "name", campaign_id),
                    items_count=items_count,
                    deadline=deadline_str,
                    review_link=review_link,
                )
                return True
        return False

    return _run_async(_send())
