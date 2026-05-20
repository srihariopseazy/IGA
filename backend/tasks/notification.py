import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from backend.celery_app import celery_app
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _send_notification_async(notification_id: str, channel: str) -> dict:
    """
    Load a Notification record and dispatch it via the specified channel.
    Supported channels: email, websocket, slack.
    """
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import Notification

            stmt = select(Notification).where(Notification.id == notification_id)
            result = await session.execute(stmt)
            notification = result.scalar_one_or_none()

            if notification is None:
                logger.error("Notification %s not found", notification_id)
                return {"status": "not_found"}

            if getattr(notification, "status", "") == "sent":
                return {"status": "already_sent"}

            payload = getattr(notification, "payload", {}) or {}
            tenant_id = str(getattr(notification, "tenant_id", ""))
            user_id = str(getattr(notification, "user_id", ""))
            title = getattr(notification, "title", "Notification")
            body = getattr(notification, "body", "")

            success = False

            if channel == "email":
                email = payload.get("email") or payload.get("to")
                if email:
                    from backend.utils.email import email_service
                    success = await email_service.send_email(
                        to=[email],
                        subject=title,
                        html_body=f"<p>{body}</p>",
                        text_body=body,
                    )

            elif channel == "websocket":
                from backend.utils.websocket_manager import ws_manager
                message = {
                    "type": "notification",
                    "notification_id": notification_id,
                    "title": title,
                    "body": body,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": payload,
                }
                await ws_manager.send_personal_message(message, tenant_id, user_id)
                success = True

            elif channel == "slack":
                # Placeholder for Slack integration
                webhook_url = payload.get("slack_webhook_url")
                if webhook_url:
                    import aiohttp
                    async with aiohttp.ClientSession() as http:
                        resp = await http.post(webhook_url, json={"text": f"*{title}*\n{body}"})
                        success = resp.status == 200
                else:
                    logger.warning("No slack_webhook_url in notification %s payload", notification_id)

            # Update notification status
            notification.status = "sent" if success else "failed"
            notification.sent_at = datetime.now(timezone.utc) if success else None
            await session.commit()

            return {"notification_id": notification_id, "channel": channel, "success": success}

        except Exception as exc:
            await session.rollback()
            logger.error(
                "send_notification error for %s via %s: %s", notification_id, channel, exc,
                exc_info=True,
            )
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.notification.send_notification",
    queue="notification",
)
def send_notification(notification_id: str, channel: str) -> dict:
    """Load and dispatch a notification record via email, websocket, or slack."""
    return _run_async(_send_notification_async(notification_id, channel))


async def _send_approval_reminder_async(approval_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        try:
            from backend.models.application import ApprovalStep, AccessRequest
            from backend.models.user import User
            from backend.config import settings as cfg

            stmt = select(ApprovalStep).where(ApprovalStep.id == approval_id)
            result = await session.execute(stmt)
            approval = result.scalar_one_or_none()

            if approval is None:
                logger.warning("ApprovalStep %s not found", approval_id)
                return {"status": "not_found"}

            if getattr(approval, "status", "") != "pending":
                return {"status": "not_pending"}

            approver_id = str(getattr(approval, "approver_id", ""))
            request_id = str(getattr(approval, "access_request_id", ""))

            # Load approver
            user_result = await session.execute(select(User).where(User.id == approver_id))
            approver = user_result.scalar_one_or_none()

            # Load request
            req_result = await session.execute(select(AccessRequest).where(AccessRequest.id == request_id))
            request = req_result.scalar_one_or_none()

            if approver and request:
                from backend.utils.email import email_service
                requester_id = str(getattr(request, "requester_id", ""))
                req_user_result = await session.execute(select(User).where(User.id == requester_id))
                requester = req_user_result.scalar_one_or_none()
                requester_name = (
                    f"{requester.first_name} {requester.last_name}" if requester else "Unknown"
                )
                approve_link = f"{cfg.FRONTEND_URL}/approvals/{approval_id}?action=approve"
                reject_link = f"{cfg.FRONTEND_URL}/approvals/{approval_id}?action=reject"
                await email_service.send_approval_request(
                    approver_email=approver.email,
                    requester_name=requester_name,
                    request_details={"request_id": request_id, "justification": getattr(request, "justification", "")},
                    approve_link=approve_link,
                    reject_link=reject_link,
                )
                return {"status": "sent", "approval_id": approval_id}

            return {"status": "user_or_request_not_found"}

        except Exception as exc:
            logger.error("send_approval_reminder error for %s: %s", approval_id, exc, exc_info=True)
            return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.notification.send_approval_reminder",
    queue="notification",
)
def send_approval_reminder(approval_id: str) -> dict:
    """Send a reminder email for a pending approval step."""
    return _run_async(_send_approval_reminder_async(approval_id))


async def _broadcast_security_alert_async(tenant_id: str, alert_data: dict) -> dict:
    """
    Broadcast a security alert to all connected users in a tenant and
    send email alerts to affected users.
    """
    try:
        # WebSocket broadcast
        from backend.utils.websocket_manager import ws_manager
        message = {
            "type": "security_alert",
            "tenant_id": tenant_id,
            "alert_type": alert_data.get("alert_type", "security_event"),
            "severity": alert_data.get("severity", "high"),
            "details": alert_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await ws_manager.broadcast_to_tenant(message, tenant_id)

        # Email affected user if specified
        target_user_id = alert_data.get("user_id")
        if target_user_id:
            async with AsyncSessionLocal() as session:
                from backend.models.user import User
                result = await session.execute(select(User).where(User.id == target_user_id))
                user = result.scalar_one_or_none()
                if user:
                    from backend.utils.email import email_service
                    await email_service.send_security_alert(
                        user_email=user.email,
                        alert_type=alert_data.get("alert_type", "Security Event"),
                        details=alert_data,
                    )

        return {"status": "broadcasted", "tenant_id": tenant_id}

    except Exception as exc:
        logger.error(
            "broadcast_security_alert error for tenant %s: %s", tenant_id, exc, exc_info=True
        )
        return {"error": str(exc)}


@celery_app.task(
    name="backend.tasks.notification.broadcast_security_alert",
    queue="notification",
)
def broadcast_security_alert(tenant_id: str, alert_data: dict) -> dict:
    """Broadcast a security alert to all users in a tenant via WebSocket and email."""
    return _run_async(_broadcast_security_alert_async(tenant_id, alert_data))
