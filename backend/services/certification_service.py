import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.certification import (
    CertificationCampaign,
    CertificationItem,
    CertificationReviewer,
)
from backend.models.user import User

logger = logging.getLogger(__name__)


class CertificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_campaign(
        self,
        data: Dict[str, Any],
        created_by: str,
        tenant_id: str,
    ) -> CertificationCampaign:
        """Create a new certification campaign in draft state."""
        from backend.config import settings

        deadline_days = data.get(
            "deadline_days", settings.CERTIFICATION_DEFAULT_DEADLINE_DAYS
        )
        start_date = data.get("start_date") or datetime.now(timezone.utc)
        deadline = data.get("deadline") or (
            datetime.now(timezone.utc) + timedelta(days=deadline_days)
        )

        campaign = CertificationCampaign(
            tenant_id=tenant_id,
            name=data["name"],
            description=data.get("description", ""),
            campaign_type=data.get("campaign_type", "manager"),
            status="draft",
            scope_definition=data.get("scope_definition", {}),
            start_date=start_date,
            deadline=deadline,
            auto_revoke_on_expire=data.get("auto_revoke_on_expire", False),
            created_by=created_by,
        )
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        logger.info("Created certification campaign %s for tenant %s", campaign.id, tenant_id)
        return campaign

    async def start_campaign(self, campaign_id: str, tenant_id: str) -> CertificationCampaign:
        """Start a campaign: generate items, notify reviewers, set status to active."""
        result = await self.db.execute(
            select(CertificationCampaign).where(
                and_(
                    CertificationCampaign.id == campaign_id,
                    CertificationCampaign.tenant_id == tenant_id,
                )
            )
        )
        campaign = result.scalar_one_or_none()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign.status != "draft":
            raise ValueError(f"Campaign must be in draft state to start (current: {campaign.status})")

        items_count = await self.generate_items(campaign, tenant_id)
        campaign.status = "active"
        campaign.start_date = datetime.now(timezone.utc)
        await self.db.commit()

        # Send notifications to reviewers
        try:
            await self._notify_reviewers(campaign, tenant_id)
        except Exception as e:
            logger.error("Failed to send reviewer notifications: %s", e)

        logger.info(
            "Started campaign %s with %d items", campaign_id, items_count
        )
        return campaign

    async def generate_items(
        self, campaign: CertificationCampaign, tenant_id: str
    ) -> int:
        """
        Generate CertificationItem records based on campaign type and scope.
        Returns number of items created.
        """
        from backend.models.rbac import UserRole, Role

        scope = campaign.scope_definition or {}
        items_created = 0

        if campaign.campaign_type == "manager":
            # For each user, create items for all their roles; assign to their manager
            users_query = select(User).where(
                and_(
                    User.tenant_id == tenant_id,
                    User.status == "active",
                    User.deleted_at.is_(None),
                )
            )
            if scope.get("department_ids"):
                users_query = users_query.where(
                    User.department_id.in_(scope["department_ids"])
                )
            if scope.get("user_ids"):
                users_query = users_query.where(User.id.in_(scope["user_ids"]))

            users_result = await self.db.execute(users_query)
            users = users_result.scalars().all()

            for user in users:
                reviewer_id = user.manager_id or campaign.created_by
                roles_result = await self.db.execute(
                    select(UserRole).where(
                        and_(
                            UserRole.user_id == user.id,
                            UserRole.tenant_id == tenant_id,
                            UserRole.deleted_at.is_(None),
                        )
                    )
                )
                user_roles = roles_result.scalars().all()

                for ur in user_roles:
                    item = CertificationItem(
                        campaign_id=campaign.id,
                        tenant_id=tenant_id,
                        user_id=user.id,
                        item_type="role",
                        item_id=ur.role_id,
                        reviewer_id=reviewer_id,
                        status="pending",
                    )
                    self.db.add(item)
                    items_created += 1

                    # Register reviewer
                    await self._ensure_reviewer(campaign.id, reviewer_id, tenant_id)

        elif campaign.campaign_type == "role_owner":
            # For each role, create items; assign to role created_by as reviewer
            roles_query = select(Role).where(
                and_(Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
            )
            if scope.get("role_ids"):
                roles_query = roles_query.where(Role.id.in_(scope["role_ids"]))

            roles_result = await self.db.execute(roles_query)
            roles = roles_result.scalars().all()

            for role in roles:
                reviewer_id = role.created_by or campaign.created_by
                role_users_result = await self.db.execute(
                    select(UserRole.user_id).where(
                        and_(
                            UserRole.role_id == role.id,
                            UserRole.tenant_id == tenant_id,
                            UserRole.deleted_at.is_(None),
                        )
                    )
                )
                for (user_id,) in role_users_result.all():
                    item = CertificationItem(
                        campaign_id=campaign.id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        item_type="role",
                        item_id=role.id,
                        reviewer_id=reviewer_id,
                        status="pending",
                    )
                    self.db.add(item)
                    items_created += 1

                    await self._ensure_reviewer(campaign.id, reviewer_id, tenant_id)

        elif campaign.campaign_type in ("app_owner", "entitlement"):
            # Generic: create items for all user-application assignments
            from backend.models.application import Application

            apps_query = select(Application).where(
                and_(Application.tenant_id == tenant_id, Application.deleted_at.is_(None))
            )
            if scope.get("application_ids"):
                apps_query = apps_query.where(
                    Application.id.in_(scope["application_ids"])
                )
            apps_result = await self.db.execute(apps_query)
            apps = apps_result.scalars().all()

            for app in apps:
                reviewer_id = app.owner_id or campaign.created_by
                # Get all users with access to this app (via roles)
                users_result = await self.db.execute(
                    select(User).where(
                        and_(
                            User.tenant_id == tenant_id,
                            User.status == "active",
                            User.deleted_at.is_(None),
                        )
                    )
                )
                for user in users_result.scalars().all():
                    item = CertificationItem(
                        campaign_id=campaign.id,
                        tenant_id=tenant_id,
                        user_id=user.id,
                        item_type="application",
                        item_id=app.id,
                        reviewer_id=reviewer_id,
                        status="pending",
                    )
                    self.db.add(item)
                    items_created += 1
                    await self._ensure_reviewer(campaign.id, reviewer_id, tenant_id)

        await self.db.commit()
        return items_created

    async def _ensure_reviewer(
        self, campaign_id, reviewer_id: Optional[str], tenant_id: str
    ) -> None:
        """Ensure a reviewer record exists for this campaign."""
        if not reviewer_id:
            return
        existing = await self.db.execute(
            select(CertificationReviewer).where(
                and_(
                    CertificationReviewer.campaign_id == campaign_id,
                    CertificationReviewer.reviewer_id == reviewer_id,
                )
            )
        )
        if not existing.scalar_one_or_none():
            reviewer = CertificationReviewer(
                campaign_id=campaign_id,
                tenant_id=tenant_id,
                reviewer_id=reviewer_id,
                items_assigned=0,
                items_completed=0,
            )
            self.db.add(reviewer)

    async def certify_item(
        self,
        item_id: str,
        reviewer_id: str,
        reason: Optional[str],
        tenant_id: str,
    ) -> CertificationItem:
        """Mark a certification item as certified."""
        result = await self.db.execute(
            select(CertificationItem).where(
                and_(
                    CertificationItem.id == item_id,
                    CertificationItem.tenant_id == tenant_id,
                )
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"Certification item {item_id} not found")
        if item.status != "pending":
            raise ValueError(f"Item is not in pending state (current: {item.status})")

        item.status = "certified"
        item.reviewer_id = reviewer_id
        item.decision_reason = reason
        item.decided_at = datetime.now(timezone.utc)

        await self._update_reviewer_progress(item.campaign_id, reviewer_id)
        await self.db.commit()
        return item

    async def revoke_item(
        self,
        item_id: str,
        reviewer_id: str,
        reason: Optional[str],
        tenant_id: str,
    ) -> CertificationItem:
        """Mark a certification item as revoked and trigger deprovisioning."""
        result = await self.db.execute(
            select(CertificationItem).where(
                and_(
                    CertificationItem.id == item_id,
                    CertificationItem.tenant_id == tenant_id,
                )
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"Certification item {item_id} not found")
        if item.status != "pending":
            raise ValueError(f"Item is not in pending state (current: {item.status})")

        item.status = "revoked"
        item.reviewer_id = reviewer_id
        item.decision_reason = reason
        item.decided_at = datetime.now(timezone.utc)

        await self._update_reviewer_progress(item.campaign_id, reviewer_id)
        await self.db.commit()

        # Trigger deprovisioning
        try:
            await self._trigger_revocation(item, tenant_id)
        except Exception as e:
            logger.error("Failed to trigger revocation for item %s: %s", item_id, e)

        return item

    async def _trigger_revocation(
        self, item: CertificationItem, tenant_id: str
    ) -> None:
        """Remove user's access (role or application) after revocation decision."""
        if item.item_type == "role":
            from backend.models.rbac import UserRole

            result = await self.db.execute(
                select(UserRole).where(
                    and_(
                        UserRole.user_id == item.user_id,
                        UserRole.role_id == item.item_id,
                        UserRole.tenant_id == tenant_id,
                        UserRole.deleted_at.is_(None),
                    )
                )
            )
            user_role = result.scalar_one_or_none()
            if user_role:
                user_role.soft_delete()
                await self.db.commit()
                logger.info(
                    "Revoked role %s from user %s due to certification",
                    item.item_id,
                    item.user_id,
                )

    async def _update_reviewer_progress(
        self, campaign_id, reviewer_id: str
    ) -> None:
        """Update reviewer's items_completed counter."""
        completed_count_result = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                and_(
                    CertificationItem.campaign_id == campaign_id,
                    CertificationItem.reviewer_id == reviewer_id,
                    CertificationItem.status.in_(["certified", "revoked"]),
                )
            )
        )
        completed = completed_count_result.scalar() or 0

        reviewer_result = await self.db.execute(
            select(CertificationReviewer).where(
                and_(
                    CertificationReviewer.campaign_id == campaign_id,
                    CertificationReviewer.reviewer_id == reviewer_id,
                )
            )
        )
        reviewer = reviewer_result.scalar_one_or_none()
        if reviewer:
            reviewer.items_completed = completed

    async def get_campaign_stats(
        self, campaign_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        """Return detailed stats for a certification campaign."""
        result = await self.db.execute(
            select(CertificationCampaign).where(
                and_(
                    CertificationCampaign.id == campaign_id,
                    CertificationCampaign.tenant_id == tenant_id,
                )
            )
        )
        campaign = result.scalar_one_or_none()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        total_result = await self.db.execute(
            select(func.count(CertificationItem.id)).where(
                CertificationItem.campaign_id == campaign_id
            )
        )
        total = total_result.scalar() or 0

        by_status_result = await self.db.execute(
            select(CertificationItem.status, func.count(CertificationItem.id))
            .where(CertificationItem.campaign_id == campaign_id)
            .group_by(CertificationItem.status)
        )
        by_status = {row[0]: row[1] for row in by_status_result.all()}

        pending = by_status.get("pending", 0)
        certified = by_status.get("certified", 0)
        revoked = by_status.get("revoked", 0)
        escalated = by_status.get("escalated", 0)
        completed = certified + revoked + escalated
        completion_pct = round(completed / total * 100, 1) if total > 0 else 0

        now = datetime.now(timezone.utc)
        days_remaining = None
        if campaign.deadline:
            delta = campaign.deadline - now
            days_remaining = max(0, delta.days)

        return {
            "campaign_id": str(campaign_id),
            "campaign_name": campaign.name,
            "status": campaign.status,
            "total_items": total,
            "pending": pending,
            "certified": certified,
            "revoked": revoked,
            "escalated": escalated,
            "completion_percentage": completion_pct,
            "days_remaining": days_remaining,
            "deadline": campaign.deadline.isoformat() if campaign.deadline else None,
        }

    async def check_deadlines(self, tenant_id: Optional[str] = None) -> None:
        """
        Check active campaigns for deadline issues.
        Send reminders, escalate overdue items, auto-revoke if configured.
        """
        from backend.config import settings

        campaigns_query = select(CertificationCampaign).where(
            CertificationCampaign.status == "active"
        )
        if tenant_id:
            campaigns_query = campaigns_query.where(
                CertificationCampaign.tenant_id == tenant_id
            )
        campaigns_result = await self.db.execute(campaigns_query)
        campaigns = campaigns_result.scalars().all()

        now = datetime.now(timezone.utc)
        escalation_threshold = timedelta(days=settings.CERTIFICATION_ESCALATION_DAYS)

        for campaign in campaigns:
            if not campaign.deadline:
                continue

            time_until_deadline = campaign.deadline - now
            is_overdue = time_until_deadline.total_seconds() < 0
            is_near_deadline = (
                timedelta(0) < time_until_deadline <= escalation_threshold
            )

            if is_overdue:
                # Auto-revoke if configured
                if campaign.auto_revoke_on_expire:
                    await self._auto_revoke_pending(campaign, str(campaign.tenant_id))
                # Mark campaign completed
                campaign.status = "completed"
                logger.info("Campaign %s deadline passed; marked completed", campaign.id)

            elif is_near_deadline:
                # Send deadline reminders
                try:
                    await self._send_deadline_reminders(campaign, str(campaign.tenant_id))
                except Exception as e:
                    logger.error("Failed to send reminders for campaign %s: %s", campaign.id, e)

        await self.db.commit()

    async def _auto_revoke_pending(
        self, campaign: CertificationCampaign, tenant_id: str
    ) -> None:
        """Auto-revoke all pending items when campaign expires."""
        result = await self.db.execute(
            select(CertificationItem).where(
                and_(
                    CertificationItem.campaign_id == campaign.id,
                    CertificationItem.status == "pending",
                )
            )
        )
        pending_items = result.scalars().all()
        for item in pending_items:
            item.status = "revoked"
            item.decision_reason = "Auto-revoked: certification deadline passed"
            item.decided_at = datetime.now(timezone.utc)
            try:
                await self._trigger_revocation(item, tenant_id)
            except Exception as e:
                logger.error("Auto-revocation failed for item %s: %s", item.id, e)
        logger.info(
            "Auto-revoked %d items for expired campaign %s", len(pending_items), campaign.id
        )

    async def _send_deadline_reminders(
        self, campaign: CertificationCampaign, tenant_id: str
    ) -> None:
        """Send reminder notifications to reviewers with pending items."""
        from backend.models.notification import Notification

        reviewers_result = await self.db.execute(
            select(CertificationReviewer).where(
                CertificationReviewer.campaign_id == campaign.id
            )
        )
        reviewers = reviewers_result.scalars().all()
        for reviewer in reviewers:
            if reviewer.reviewer_id and reviewer.items_completed < reviewer.items_assigned:
                notification = Notification(
                    tenant_id=tenant_id,
                    user_id=reviewer.reviewer_id,
                    notification_type="certification_reminder",
                    title=f"Action Required: {campaign.name}",
                    message=(
                        f"You have {reviewer.items_assigned - reviewer.items_completed} "
                        f"pending certification items in '{campaign.name}'. "
                        f"Deadline: {campaign.deadline.strftime('%Y-%m-%d') if campaign.deadline else 'N/A'}"
                    ),
                    reference_type="certification_campaign",
                    reference_id=campaign.id,
                )
                self.db.add(notification)

    async def _notify_reviewers(
        self, campaign: CertificationCampaign, tenant_id: str
    ) -> None:
        """Send initial notifications to all reviewers when campaign starts."""
        from backend.models.notification import Notification

        reviewers_result = await self.db.execute(
            select(CertificationReviewer).where(
                CertificationReviewer.campaign_id == campaign.id
            )
        )
        reviewers = reviewers_result.scalars().all()
        for reviewer in reviewers:
            if reviewer.reviewer_id:
                notification = Notification(
                    tenant_id=tenant_id,
                    user_id=reviewer.reviewer_id,
                    notification_type="certification_started",
                    title=f"Certification Campaign: {campaign.name}",
                    message=(
                        f"You have been assigned items to review in certification campaign "
                        f"'{campaign.name}'. Please complete your review by "
                        f"{campaign.deadline.strftime('%Y-%m-%d') if campaign.deadline else 'the deadline'}."
                    ),
                    reference_type="certification_campaign",
                    reference_id=campaign.id,
                )
                self.db.add(notification)
        await self.db.commit()

    async def export_results(self, campaign_id: str, tenant_id: str) -> str:
        """
        Export certification results to CSV, upload to MinIO, return presigned URL.
        """
        result = await self.db.execute(
            select(CertificationCampaign).where(
                and_(
                    CertificationCampaign.id == campaign_id,
                    CertificationCampaign.tenant_id == tenant_id,
                )
            )
        )
        campaign = result.scalar_one_or_none()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        items_result = await self.db.execute(
            select(CertificationItem).where(
                CertificationItem.campaign_id == campaign_id
            )
        )
        items = items_result.scalars().all()

        # Build CSV
        output = io.StringIO()
        fieldnames = [
            "id",
            "user_id",
            "item_type",
            "item_id",
            "reviewer_id",
            "status",
            "decision_reason",
            "decided_at",
            "created_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            row = {k: str(getattr(item, k, "") or "") for k in fieldnames}
            writer.writerow(row)

        csv_bytes = output.getvalue().encode("utf-8")
        object_name = f"certifications/{campaign_id}/results_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

        # Upload to MinIO
        try:
            from minio import Minio
            from datetime import timedelta as td
            from backend.config import settings
            import io as _io

            client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            # Ensure bucket exists
            if not client.bucket_exists(settings.MINIO_BUCKET):
                client.make_bucket(settings.MINIO_BUCKET)

            client.put_object(
                settings.MINIO_BUCKET,
                object_name,
                _io.BytesIO(csv_bytes),
                length=len(csv_bytes),
                content_type="text/csv",
            )
            presigned_url = client.presigned_get_object(
                settings.MINIO_BUCKET,
                object_name,
                expires=td(hours=24),
            )
            return presigned_url
        except Exception as e:
            logger.error("Failed to upload certification export to MinIO: %s", e)
            # Return data URL as fallback
            import base64
            b64 = base64.b64encode(csv_bytes).decode("utf-8")
            return f"data:text/csv;base64,{b64}"
