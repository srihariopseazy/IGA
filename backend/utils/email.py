import logging
from typing import List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib
from jinja2 import Environment, BaseLoader, Template
from backend.config import settings

logger = logging.getLogger(__name__)


WELCOME_HTML = """
<!DOCTYPE html><html><body>
<h2>Welcome to {{ tenant_name }}, {{ user_name }}!</h2>
<p>Your account has been created.</p>
{% if temp_password %}<p>Your temporary password is: <strong>{{ temp_password }}</strong></p><p>Please change it on first login.</p>{% endif %}
<p>Login at: <a href="{{ frontend_url }}">{{ frontend_url }}</a></p>
</body></html>
"""

MAGIC_LINK_HTML = """
<!DOCTYPE html><html><body>
<h2>Sign in to {{ tenant_name }}</h2>
<p>Click the link below to sign in. This link expires in {{ expire_minutes }} minutes.</p>
<p><a href="{{ magic_link }}">Sign In</a></p>
<p>If you did not request this, ignore this email.</p>
</body></html>
"""

PASSWORD_RESET_HTML = """
<!DOCTYPE html><html><body>
<h2>Password Reset Request</h2>
<p>Click the link below to reset your password. This link expires in 15 minutes.</p>
<p><a href="{{ reset_link }}">Reset Password</a></p>
<p>If you did not request this, ignore this email.</p>
</body></html>
"""

MFA_OTP_HTML = """
<!DOCTYPE html><html><body>
<h2>Your One-Time Password</h2>
<p>Your OTP code is: <strong>{{ otp }}</strong></p>
<p>This code expires in {{ validity_seconds }} seconds.</p>
</body></html>
"""

APPROVAL_REQUEST_HTML = """
<!DOCTYPE html><html><body>
<h2>Access Request Pending Your Approval</h2>
<p><strong>{{ requester_name }}</strong> has submitted an access request that requires your approval.</p>
<h3>Request Details:</h3>
<ul>
{% for key, value in details.items() %}<li><strong>{{ key }}</strong>: {{ value }}</li>{% endfor %}
</ul>
<p>
  <a href="{{ approve_link }}" style="background:#22c55e;color:white;padding:10px 20px;text-decoration:none;">Approve</a>
  &nbsp;&nbsp;
  <a href="{{ reject_link }}" style="background:#ef4444;color:white;padding:10px 20px;text-decoration:none;">Reject</a>
</p>
</body></html>
"""

ACCESS_APPROVED_HTML = """
<!DOCTYPE html><html><body>
<h2>Access Request Approved</h2>
<p>Your access request has been approved.</p>
<h3>Details:</h3>
<ul>
{% for key, value in details.items() %}<li><strong>{{ key }}</strong>: {{ value }}</li>{% endfor %}
</ul>
</body></html>
"""

ACCESS_REJECTED_HTML = """
<!DOCTYPE html><html><body>
<h2>Access Request Rejected</h2>
<p>Your access request has been rejected.</p>
{% if reason %}<p><strong>Reason:</strong> {{ reason }}</p>{% endif %}
</body></html>
"""

CERTIFICATION_REMINDER_HTML = """
<!DOCTYPE html><html><body>
<h2>Certification Reminder: {{ campaign_name }}</h2>
<p>You have <strong>{{ items_count }}</strong> items pending review in the <em>{{ campaign_name }}</em> campaign.</p>
<p><strong>Deadline:</strong> {{ deadline }}</p>
<p><a href="{{ review_link }}">Review Now</a></p>
</body></html>
"""

SECURITY_ALERT_HTML = """
<!DOCTYPE html><html><body>
<h2>Security Alert: {{ alert_type }}</h2>
<p>A security event has been detected on your account.</p>
<h3>Details:</h3>
<ul>
{% for key, value in details.items() %}<li><strong>{{ key }}</strong>: {{ value }}</li>{% endfor %}
</ul>
<p>If this was not you, please contact your administrator immediately.</p>
</body></html>
"""

jinja_env = Environment(loader=BaseLoader())


def render_template(template_str: str, **kwargs) -> str:
    tmpl: Template = jinja_env.from_string(template_str)
    return tmpl.render(**kwargs)


class EmailService:
    """Async email service using aiosmtplib."""

    async def send_email(
        self,
        to: List[str],
        subject: str,
        html_body: str,
        text_body: str = "",
    ) -> bool:
        """Send an email to one or more recipients."""
        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = settings.SMTP_FROM
            message["To"] = ", ".join(to)

            if text_body:
                message.attach(MIMEText(text_body, "plain", "utf-8"))
            message.attach(MIMEText(html_body, "html", "utf-8"))

            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER if settings.SMTP_USER else None,
                password=settings.SMTP_PASSWORD if settings.SMTP_PASSWORD else None,
                use_tls=settings.SMTP_TLS,
            )
            logger.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return False

    async def send_welcome_email(
        self,
        user_email: str,
        user_name: str,
        tenant_name: str,
        temp_password: Optional[str] = None,
    ) -> bool:
        html = render_template(
            WELCOME_HTML,
            user_name=user_name,
            tenant_name=tenant_name,
            temp_password=temp_password,
            frontend_url=settings.FRONTEND_URL,
        )
        text = f"Welcome to {tenant_name}, {user_name}! Login at {settings.FRONTEND_URL}"
        return await self.send_email(
            to=[user_email],
            subject=f"Welcome to {tenant_name}",
            html_body=html,
            text_body=text,
        )

    async def send_magic_link(
        self,
        email: str,
        magic_link: str,
        tenant_name: str,
    ) -> bool:
        html = render_template(
            MAGIC_LINK_HTML,
            tenant_name=tenant_name,
            magic_link=magic_link,
            expire_minutes=settings.MAGIC_LINK_EXPIRE_MINUTES,
        )
        text = f"Sign in to {tenant_name}: {magic_link}"
        return await self.send_email(
            to=[email],
            subject=f"Sign in to {tenant_name}",
            html_body=html,
            text_body=text,
        )

    async def send_password_reset(self, email: str, reset_link: str) -> bool:
        html = render_template(PASSWORD_RESET_HTML, reset_link=reset_link)
        text = f"Reset your password: {reset_link}"
        return await self.send_email(
            to=[email],
            subject="Password Reset Request",
            html_body=html,
            text_body=text,
        )

    async def send_mfa_otp(self, email: str, otp: str) -> bool:
        html = render_template(
            MFA_OTP_HTML,
            otp=otp,
            validity_seconds=settings.MFA_OTP_VALIDITY_SECONDS,
        )
        text = f"Your OTP code is: {otp}. Valid for {settings.MFA_OTP_VALIDITY_SECONDS} seconds."
        return await self.send_email(
            to=[email],
            subject="Your One-Time Password",
            html_body=html,
            text_body=text,
        )

    async def send_approval_request(
        self,
        approver_email: str,
        requester_name: str,
        request_details: dict,
        approve_link: str,
        reject_link: str,
    ) -> bool:
        html = render_template(
            APPROVAL_REQUEST_HTML,
            requester_name=requester_name,
            details=request_details,
            approve_link=approve_link,
            reject_link=reject_link,
        )
        text = f"Access request from {requester_name} pending your approval. Approve: {approve_link}"
        return await self.send_email(
            to=[approver_email],
            subject=f"Access Request from {requester_name} Requires Your Approval",
            html_body=html,
            text_body=text,
        )

    async def send_access_approved(
        self,
        user_email: str,
        access_details: dict,
    ) -> bool:
        html = render_template(ACCESS_APPROVED_HTML, details=access_details)
        text = "Your access request has been approved."
        return await self.send_email(
            to=[user_email],
            subject="Your Access Request Has Been Approved",
            html_body=html,
            text_body=text,
        )

    async def send_access_rejected(self, user_email: str, reason: str) -> bool:
        html = render_template(ACCESS_REJECTED_HTML, reason=reason)
        text = f"Your access request has been rejected. Reason: {reason}"
        return await self.send_email(
            to=[user_email],
            subject="Your Access Request Has Been Rejected",
            html_body=html,
            text_body=text,
        )

    async def send_certification_reminder(
        self,
        reviewer_email: str,
        campaign_name: str,
        items_count: int,
        deadline: str,
        review_link: str,
    ) -> bool:
        html = render_template(
            CERTIFICATION_REMINDER_HTML,
            campaign_name=campaign_name,
            items_count=items_count,
            deadline=deadline,
            review_link=review_link,
        )
        text = (
            f"Certification Reminder: {campaign_name}. "
            f"{items_count} items pending. Deadline: {deadline}. "
            f"Review: {review_link}"
        )
        return await self.send_email(
            to=[reviewer_email],
            subject=f"Certification Reminder: {campaign_name}",
            html_body=html,
            text_body=text,
        )

    async def send_security_alert(
        self,
        user_email: str,
        alert_type: str,
        details: dict,
    ) -> bool:
        html = render_template(
            SECURITY_ALERT_HTML,
            alert_type=alert_type,
            details=details,
        )
        text = f"Security Alert: {alert_type}. Details: {details}"
        return await self.send_email(
            to=[user_email],
            subject=f"Security Alert: {alert_type}",
            html_body=html,
            text_body=text,
        )


email_service = EmailService()

async def send_email(to, subject, html_body, text_body=''):
    return await email_service.send_email(to=[to] if isinstance(to, str) else to, subject=subject, html_body=html_body, text_body=text_body)
