from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_
from datetime import datetime, timedelta, timezone
import pyotp
import qrcode
import base64
import io
import secrets
import hashlib
from typing import Optional, Dict, Any, List, Tuple
import logging

from backend.models.user import User, Session, MFADevice, LoginHistory, PasswordResetToken, EmailVerificationToken, OTPCode
from backend.models.tenant import Tenant
from backend.utils.security import hash_password, verify_password, encrypt_field, decrypt_field, generate_secure_token, hash_token, verify_token_hash
from backend.utils.jwt_utils import create_access_token, create_refresh_token, decode_token
from backend.utils.redis_client import redis_client
from backend.utils.email import EmailService
from backend.config import settings

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService()

    async def login(
        self,
        email: str,
        password: str,
        tenant_slug: str,
        ip_address: str,
        user_agent: str,
        device_fingerprint: str,
        mfa_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1. Get tenant
        tenant = await self._get_tenant_by_slug(tenant_slug)
        if not tenant or tenant.status != "active":
            raise ValueError("Invalid tenant or tenant is suspended")

        # 2. Get user
        user = await self._get_user_by_email(email, tenant.id)
        if not user:
            await self._record_login_history(None, tenant.id, ip_address, user_agent, device_fingerprint, False, "User not found")
            raise ValueError("Invalid credentials")

        # 3. Check lockout
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise ValueError(f"Account locked until {user.locked_until.isoformat()}")

        # 4. Verify password
        if not verify_password(password, user.hashed_password):
            await redis_client.track_failed_login(str(user.id))
            count = await redis_client.get_failed_logins(str(user.id))
            if count >= settings.MAX_LOGIN_ATTEMPTS:
                locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
                await self.db.execute(
                    update(User).where(User.id == user.id).values(locked_until=locked_until, failed_login_attempts=count)
                )
                await self.db.commit()
            await self._record_login_history(user.id, tenant.id, ip_address, user_agent, device_fingerprint, False, "Invalid password")
            raise ValueError("Invalid credentials")

        # 5. Check user status
        if user.status not in ["active"]:
            raise ValueError(f"Account is {user.status}")

        # 6. MFA check
        if user.mfa_enabled:
            if not mfa_code:
                return {"requires_mfa": True, "user_id": str(user.id)}
            mfa_valid = await self._verify_mfa(user, mfa_code)
            if not mfa_valid:
                await self._record_login_history(user.id, tenant.id, ip_address, user_agent, device_fingerprint, False, "Invalid MFA code")
                raise ValueError("Invalid MFA code")

        # 7. Anomaly detection
        await self._check_login_anomaly(user, ip_address, device_fingerprint, tenant.id)

        # 8. Create session
        session = await self._create_session(user, tenant.id, ip_address, user_agent, device_fingerprint)

        # 9. Generate tokens
        token_data = {
            "sub": str(user.id),
            "tenant_id": str(tenant.id),
            "email": user.email,
            "jti": str(session.id),
        }
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(str(user.id), str(tenant.id), str(session.id))

        # 10. Clear failed logins
        await redis_client.clear_failed_logins(str(user.id))

        # 11. Update last_login
        await self.db.execute(
            update(User).where(User.id == user.id).values(
                last_login_at=datetime.now(timezone.utc),
                failed_login_attempts=0,
            )
        )
        await self.db.commit()

        # 12. Record login history
        await self._record_login_history(
            user.id, tenant.id, ip_address, user_agent, device_fingerprint, True, None, mfa_used=user.mfa_enabled
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": user.display_name,
                "tenant_id": str(tenant.id),
                "mfa_enabled": user.mfa_enabled,
                "avatar_url": user.avatar_url,
            },
        }

    async def refresh_token(self, refresh_token_str: str) -> Dict[str, Any]:
        try:
            payload = decode_token(refresh_token_str)
            user_id = payload.get("sub")
            tenant_id = payload.get("tenant_id")
            jti = payload.get("jti")

            if await redis_client.is_token_blacklisted(jti):
                raise ValueError("Token has been revoked")

            # Verify session exists and is active
            result = await self.db.execute(
                select(Session).where(
                    and_(
                        Session.id == jti,
                        Session.user_id == user_id,
                        Session.is_active == True,
                        Session.expires_at > datetime.now(timezone.utc),
                    )
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                raise ValueError("Session expired or invalid")

            # Get user
            user = await self.db.get(User, user_id)
            if not user or user.status != "active":
                raise ValueError("User not found or inactive")

            # Issue new access token
            token_data = {
                "sub": str(user.id),
                "tenant_id": tenant_id,
                "email": user.email,
                "jti": jti,
            }
            new_access_token = create_access_token(token_data)

            # Update session last_active
            await self.db.execute(
                update(Session).where(Session.id == session.id).values(last_active_at=datetime.now(timezone.utc))
            )
            await self.db.commit()

            return {
                "access_token": new_access_token,
                "token_type": "bearer",
                "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            }
        except Exception as e:
            raise ValueError(f"Invalid refresh token: {str(e)}")

    async def logout(self, jti: str, expire_seconds: int = None):
        if expire_seconds is None:
            expire_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        await redis_client.blacklist_token(jti, expire_seconds)
        # Deactivate session
        await self.db.execute(
            update(Session).where(Session.id == jti).values(is_active=False)
        )
        await self.db.commit()

    async def setup_totp(self, user: User) -> Dict[str, Any]:
        secret = pyotp.random_base32()
        encrypted_secret = encrypt_field(secret, base64.b64decode(settings.ENCRYPTION_KEY))

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="IGA Platform")

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_base64 = base64.b64encode(buf.getvalue()).decode()

        # Generate backup codes
        backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
        backup_codes_hashed = [hash_token(code) for code in backup_codes]

        # Store device (unverified)
        device = MFADevice(
            user_id=user.id,
            tenant_id=user.tenant_id,
            device_type="totp",
            name="Authenticator App",
            secret_encrypted=encrypted_secret,
            is_verified=False,
        )
        self.db.add(device)

        # Store backup codes as separate device
        backup_device = MFADevice(
            user_id=user.id,
            tenant_id=user.tenant_id,
            device_type="backup_codes",
            name="Backup Codes",
            secret_encrypted="|".join(backup_codes_hashed),
            is_verified=True,
        )
        self.db.add(backup_device)
        await self.db.commit()

        return {
            "secret": secret,
            "qr_code": f"data:image/png;base64,{qr_base64}",
            "provisioning_uri": provisioning_uri,
            "backup_codes": backup_codes,
            "device_id": str(device.id),
        }

    async def verify_totp(self, user: User, code: str, device_id: str) -> bool:
        result = await self.db.execute(
            select(MFADevice).where(
                and_(
                    MFADevice.id == device_id,
                    MFADevice.user_id == user.id,
                    MFADevice.device_type == "totp",
                )
            )
        )
        device = result.scalar_one_or_none()
        if not device:
            return False

        secret = decrypt_field(device.secret_encrypted, base64.b64decode(settings.ENCRYPTION_KEY))
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            device.is_verified = True
            user.mfa_enabled = True
            await self.db.commit()
            return True
        return False

    async def disable_mfa(self, user: User, password: str) -> bool:
        if not verify_password(password, user.hashed_password):
            raise ValueError("Invalid password")

        result = await self.db.execute(
            select(MFADevice).where(
                and_(MFADevice.user_id == user.id, MFADevice.deleted_at.is_(None))
            )
        )
        devices = result.scalars().all()
        now = datetime.now(timezone.utc)
        for device in devices:
            device.deleted_at = now

        user.mfa_enabled = False
        await self.db.commit()
        return True

    async def _verify_mfa(self, user: User, code: str) -> bool:
        result = await self.db.execute(
            select(MFADevice).where(
                and_(
                    MFADevice.user_id == user.id,
                    MFADevice.is_verified == True,
                    MFADevice.deleted_at.is_(None),
                )
            )
        )
        devices = result.scalars().all()

        for device in devices:
            if device.device_type == "totp":
                secret = decrypt_field(device.secret_encrypted, base64.b64decode(settings.ENCRYPTION_KEY))
                totp = pyotp.TOTP(secret)
                if totp.verify(code, valid_window=1):
                    device.last_used_at = datetime.now(timezone.utc)
                    await self.db.commit()
                    return True
            elif device.device_type == "backup_codes":
                stored_hashes = device.secret_encrypted.split("|")
                code_hash = hash_token(code.upper())
                if code_hash in stored_hashes:
                    stored_hashes.remove(code_hash)
                    device.secret_encrypted = "|".join(stored_hashes)
                    await self.db.commit()
                    return True
        return False

    async def send_magic_link(self, email: str, tenant_slug: str) -> bool:
        tenant = await self._get_tenant_by_slug(tenant_slug)
        if not tenant:
            return True  # Don't reveal existence
        user = await self._get_user_by_email(email, tenant.id)
        if not user:
            return True

        token = generate_secure_token()
        token_hash = hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.MAGIC_LINK_EXPIRE_MINUTES)

        otp = OTPCode(
            user_id=user.id,
            tenant_id=tenant.id,
            code_hash=token_hash,
            purpose="magic_link",
            expires_at=expires_at,
        )
        self.db.add(otp)
        await self.db.commit()

        magic_link = f"{settings.FRONTEND_URL}/auth/magic-link?token={token}&tenant={tenant_slug}"
        await self.email_service.send_magic_link(email, magic_link, tenant.name)
        return True

    async def verify_magic_link(self, token: str, tenant_slug: str) -> Dict[str, Any]:
        token_hash = hash_token(token)
        tenant = await self._get_tenant_by_slug(tenant_slug)
        if not tenant:
            raise ValueError("Invalid token")

        result = await self.db.execute(
            select(OTPCode).where(
                and_(
                    OTPCode.code_hash == token_hash,
                    OTPCode.purpose == "magic_link",
                    OTPCode.tenant_id == tenant.id,
                    OTPCode.used_at.is_(None),
                    OTPCode.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        otp = result.scalar_one_or_none()
        if not otp:
            raise ValueError("Invalid or expired magic link")

        otp.used_at = datetime.now(timezone.utc)
        await self.db.commit()

        user = await self.db.get(User, otp.user_id)
        session = await self._create_session(user, tenant.id, "0.0.0.0", "Magic Link", "")

        token_data = {
            "sub": str(user.id),
            "tenant_id": str(tenant.id),
            "email": user.email,
            "jti": str(session.id),
        }
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(str(user.id), str(tenant.id), str(session.id)),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def initiate_password_reset(self, email: str, tenant_slug: str) -> bool:
        tenant = await self._get_tenant_by_slug(tenant_slug)
        if not tenant:
            return True
        user = await self._get_user_by_email(email, tenant.id)
        if not user:
            return True

        token = generate_secure_token()
        token_hash = hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=2)

        prt = PasswordResetToken(
            user_id=user.id,
            tenant_id=tenant.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(prt)
        await self.db.commit()

        reset_link = f"{settings.FRONTEND_URL}/auth/reset-password?token={token}"
        await self.email_service.send_password_reset(email, reset_link)
        return True

    async def reset_password(self, token: str, new_password: str) -> bool:
        token_hash = hash_token(token)
        result = await self.db.execute(
            select(PasswordResetToken).where(
                and_(
                    PasswordResetToken.token_hash == token_hash,
                    PasswordResetToken.used_at.is_(None),
                    PasswordResetToken.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        prt = result.scalar_one_or_none()
        if not prt:
            raise ValueError("Invalid or expired reset token")

        prt.used_at = datetime.now(timezone.utc)
        hashed = hash_password(new_password)
        await self.db.execute(
            update(User).where(User.id == prt.user_id).values(
                hashed_password=hashed,
                password_changed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()
        return True

    async def send_email_verification(self, user: User, tenant: Tenant) -> bool:
        token = generate_secure_token()
        token_hash = hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        ev_token = EmailVerificationToken(
            user_id=user.id,
            tenant_id=tenant.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(ev_token)
        await self.db.commit()

        verify_link = f"{settings.FRONTEND_URL}/auth/verify-email?token={token}"
        await self.email_service.send_email_verification(user.email, verify_link, tenant.name)
        return True

    async def verify_email(self, token: str) -> bool:
        token_hash = hash_token(token)
        result = await self.db.execute(
            select(EmailVerificationToken).where(
                and_(
                    EmailVerificationToken.token_hash == token_hash,
                    EmailVerificationToken.used_at.is_(None),
                    EmailVerificationToken.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        ev_token = result.scalar_one_or_none()
        if not ev_token:
            raise ValueError("Invalid or expired verification token")

        ev_token.used_at = datetime.now(timezone.utc)
        await self.db.execute(
            update(User).where(User.id == ev_token.user_id).values(email_verified=True)
        )
        await self.db.commit()
        return True

    async def get_active_sessions(self, user_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(Session).where(
                and_(
                    Session.user_id == user_id,
                    Session.tenant_id == tenant_id,
                    Session.is_active == True,
                    Session.expires_at > datetime.now(timezone.utc),
                )
            ).order_by(Session.last_active_at.desc())
        )
        sessions = result.scalars().all()
        return [
            {
                "id": str(s.id),
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "device_fingerprint": s.device_fingerprint,
                "created_at": s.created_at.isoformat(),
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
                "expires_at": s.expires_at.isoformat(),
            }
            for s in sessions
        ]

    async def revoke_session(self, session_id: str, user_id: str, tenant_id: str) -> bool:
        result = await self.db.execute(
            select(Session).where(
                and_(
                    Session.id == session_id,
                    Session.user_id == user_id,
                    Session.tenant_id == tenant_id,
                )
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError("Session not found")

        session.is_active = False
        await redis_client.blacklist_token(str(session.id), settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        await self.db.commit()
        return True

    async def revoke_all_sessions(self, user_id: str, tenant_id: str, except_session_id: str = None) -> int:
        query = select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.tenant_id == tenant_id,
                Session.is_active == True,
            )
        )
        result = await self.db.execute(query)
        sessions = result.scalars().all()

        revoked = 0
        for session in sessions:
            if except_session_id and str(session.id) == except_session_id:
                continue
            session.is_active = False
            await redis_client.blacklist_token(str(session.id), settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
            revoked += 1

        await self.db.commit()
        return revoked

    async def _get_tenant_by_slug(self, slug: str) -> Optional[Tenant]:
        result = await self.db.execute(
            select(Tenant).where(and_(Tenant.slug == slug, Tenant.deleted_at.is_(None)))
        )
        return result.scalar_one_or_none()

    async def _get_user_by_email(self, email: str, tenant_id) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(
                and_(
                    User.email == email.lower(),
                    User.tenant_id == tenant_id,
                    User.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def _create_session(
        self,
        user: User,
        tenant_id,
        ip_address: str,
        user_agent: str,
        device_fingerprint: str,
    ) -> Session:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session = Session(
            user_id=user.id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            expires_at=expires_at,
            last_active_at=datetime.now(timezone.utc),
            is_active=True,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def _record_login_history(
        self,
        user_id,
        tenant_id,
        ip: str,
        ua: str,
        fingerprint: str,
        success: bool,
        reason: Optional[str],
        mfa_used: bool = False,
    ):
        history = LoginHistory(
            user_id=user_id,
            tenant_id=tenant_id,
            ip_address=ip,
            user_agent=ua,
            device_fingerprint=fingerprint,
            success=success,
            failure_reason=reason,
            mfa_used=mfa_used,
        )
        self.db.add(history)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.warning("Failed to record login history", exc_info=True)

    async def _check_login_anomaly(self, user: User, ip: str, fingerprint: str, tenant_id):
        result = await self.db.execute(
            select(LoginHistory).where(
                and_(
                    LoginHistory.user_id == user.id,
                    LoginHistory.success == True,
                    LoginHistory.ip_address == ip,
                )
            ).limit(1)
        )
        known_ip = result.scalar_one_or_none()
        if not known_ip:
            try:
                await self.email_service.send_security_alert(
                    user.email,
                    "new_ip_login",
                    {"ip": ip, "time": datetime.now(timezone.utc).isoformat()},
                )
            except Exception:
                logger.warning("Failed to send security alert email", exc_info=True)
