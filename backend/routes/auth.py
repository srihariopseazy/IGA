"""
Authentication routes for the IGA platform.
Handles login, registration, MFA, OAuth, password management, and session management.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
import pyotp
import qrcode
import base64
import io
from datetime import datetime, timedelta, timezone
import secrets
import hashlib
import json

from backend.database import get_db
from backend.middleware.auth import (
    get_current_user,
    require_permission,
    create_access_token,
    create_refresh_token,
    verify_token,
    get_password_hash,
    verify_password,
    blacklist_token,
    get_redis,
)
from backend.utils.audit import log_action
from backend.models.user import User, UserSession, LoginHistory, MFABackupCode
from backend.models.tenant import Tenant
from backend.utils.email import send_email
from backend.utils.notifications import notify_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    mfa_code: Optional[str] = Field(None, max_length=8)
    device_fingerprint: Optional[str] = None
    remember_me: bool = False

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict
    mfa_required: bool = False

class RefreshRequest(BaseModel):
    refresh_token: str

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    tenant_id: str
    invitation_token: Optional[str] = None

    @validator("password")
    def password_strength(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class VerifyEmailRequest(BaseModel):
    token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    tenant_id: Optional[str] = None

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)

    @validator("new_password")
    def password_strength(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class MagicLinkRequest(BaseModel):
    email: EmailStr
    tenant_id: Optional[str] = None

class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: List[str]

class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)
    secret: Optional[str] = None

class MFADisableRequest(BaseModel):
    password: str
    code: Optional[str] = None

class OAuthRequest(BaseModel):
    code: str
    redirect_uri: str
    state: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @validator("new_password")
    def password_strength(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def _get_user_agent(request: Request) -> str:
    return request.headers.get("User-Agent", "unknown")

def _generate_device_fingerprint(request: Request) -> str:
    ua = _get_user_agent(request)
    ip = _get_client_ip(request)
    raw = f"{ua}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()

async def _check_rate_limit(redis, key: str, limit: int, window: int) -> bool:
    """Returns True if rate limit exceeded."""
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    return count > limit

async def _record_login_history(
    db: AsyncSession,
    user_id: str,
    ip_address: str,
    user_agent: str,
    success: bool,
    failure_reason: Optional[str] = None,
):
    entry = LoginHistory(
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        failure_reason=failure_reason,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Login with email/password. Supports MFA, account lockout, device fingerprint."""
    redis = await get_redis()
    ip = _get_client_ip(request)
    ua = _get_user_agent(request)

    # Rate limiting: 10 attempts per 15 minutes per IP
    rate_key = f"login_rate:{ip}"
    if await _check_rate_limit(redis, rate_key, 10, 900):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    # Fetch user
    result = await db.execute(
        select(User)
        .where(and_(User.email == body.email.lower(), User.deleted_at.is_(None)))
        .options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()

    if user is None:
        background_tasks.add_task(
            log_action, db, None, None, "login_failed", "user",
            None, {"email": body.email, "reason": "user_not_found", "ip": ip}
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds())
        background_tasks.add_task(
            _record_login_history, db, str(user.id), ip, ua, False, "account_locked"
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked. Try again in {remaining} seconds.",
        )

    # Verify password
    if not verify_password(body.password, user.hashed_password):
        # Increment failed attempts
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 10:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            user.failed_login_attempts = 0
        await db.commit()
        background_tasks.add_task(
            _record_login_history, db, str(user.id), ip, ua, False, "invalid_password"
        )
        background_tasks.add_task(
            log_action, db, str(user.id), str(user.tenant_id), "login_failed", "user",
            str(user.id), {"reason": "invalid_password", "ip": ip}
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check account status
    if user.status not in ("active", "pending_mfa"):
        background_tasks.add_task(
            _record_login_history, db, str(user.id), ip, ua, False, f"account_{user.status}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.status}",
        )

    # MFA check
    if user.mfa_enabled:
        if not body.mfa_code:
            return LoginResponse(
                access_token="",
                refresh_token="",
                expires_in=0,
                user={"id": str(user.id), "email": user.email},
                mfa_required=True,
            )
        # Verify TOTP
        totp = pyotp.TOTP(user.mfa_secret)
        backup_valid = False
        if not totp.verify(body.mfa_code, valid_window=1):
            # Check backup codes
            result_bc = await db.execute(
                select(MFABackupCode).where(
                    and_(
                        MFABackupCode.user_id == user.id,
                        MFABackupCode.used == False,
                        MFABackupCode.code_hash == hashlib.sha256(body.mfa_code.encode()).hexdigest(),
                    )
                )
            )
            backup_code = result_bc.scalar_one_or_none()
            if backup_code:
                backup_code.used = True
                backup_code.used_at = datetime.now(timezone.utc)
                await db.commit()
                backup_valid = True
            else:
                background_tasks.add_task(
                    _record_login_history, db, str(user.id), ip, ua, False, "invalid_mfa"
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    # Reset failed attempts on success
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    await db.commit()

    # Device fingerprint
    fingerprint = body.device_fingerprint or _generate_device_fingerprint(request)

    # Create tokens
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "roles": [str(r.id) for r in user.roles],
        "device": fingerprint,
    }
    expires_delta = timedelta(hours=8) if body.remember_me else timedelta(hours=1)
    access_token = create_access_token(token_data, expires_delta=expires_delta)
    refresh_token = create_refresh_token(
        {"sub": str(user.id), "tenant_id": str(user.tenant_id), "device": fingerprint},
        expires_delta=timedelta(days=30) if body.remember_me else timedelta(days=7),
    )

    # Store session
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hashlib.sha256(refresh_token.encode()).hexdigest(),
        ip_address=ip,
        user_agent=ua,
        device_fingerprint=fingerprint,
        expires_at=datetime.now(timezone.utc) + (timedelta(days=30) if body.remember_me else timedelta(days=7)),
    )
    db.add(session)
    await db.commit()

    background_tasks.add_task(
        _record_login_history, db, str(user.id), ip, ua, True
    )
    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "login_success", "user",
        str(user.id), {"ip": ip, "device": fingerprint}
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(expires_delta.total_seconds()),
        user={
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "tenant_id": str(user.tenant_id),
            "status": user.status,
            "mfa_enabled": user.mfa_enabled,
            "avatar_url": user.avatar_url,
        },
        mfa_required=False,
    )


@router.post("/refresh")
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using a valid refresh token."""
    payload = verify_token(body.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = payload.get("sub")
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()

    result = await db.execute(
        select(UserSession).where(
            and_(
                UserSession.user_id == user_id,
                UserSession.refresh_token_hash == token_hash,
                UserSession.revoked == False,
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")

    result_user = await db.execute(
        select(User)
        .where(and_(User.id == user_id, User.deleted_at.is_(None)))
        .options(selectinload(User.roles))
    )
    user = result_user.scalar_one_or_none()
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not active")

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "roles": [str(r.id) for r in user.roles],
        "device": payload.get("device"),
    }
    new_access_token = create_access_token(token_data)

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.post("/logout")
async def logout(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate the current access token and refresh session."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "")
    if token:
        payload = verify_token(token)
        if payload and payload.get("jti"):
            await blacklist_token(payload["jti"], payload.get("exp", 0))

    # Revoke the current session based on device fingerprint
    device = request.headers.get("X-Device-Fingerprint") or _generate_device_fingerprint(request)
    await db.execute(
        update(UserSession)
        .where(
            and_(
                UserSession.user_id == current_user.id,
                UserSession.device_fingerprint == device,
                UserSession.revoked == False,
            )
        )
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id), "logout", "user",
        str(current_user.id), {"ip": _get_client_ip(request)}
    )
    return {"message": "Logged out successfully"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user. Requires a valid tenant."""
    # Validate tenant
    result = await db.execute(
        select(Tenant).where(and_(Tenant.id == body.tenant_id, Tenant.status == "active"))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found or inactive")

    # Check if email already exists
    result_existing = await db.execute(
        select(User).where(
            and_(User.email == body.email.lower(), User.tenant_id == body.tenant_id)
        )
    )
    if result_existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Validate invitation token if tenant requires it
    if tenant.require_invitation and not body.invitation_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token required for this tenant",
        )

    # Create user
    email_token = secrets.token_urlsafe(32)
    user = User(
        email=body.email.lower(),
        hashed_password=get_password_hash(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        tenant_id=body.tenant_id,
        status="pending_verification",
        email_verification_token=hashlib.sha256(email_token.encode()).hexdigest(),
        email_verification_expires=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    background_tasks.add_task(
        send_email,
        to=user.email,
        subject="Verify your email address",
        template="verify_email",
        context={"token": email_token, "user": user.first_name, "tenant": tenant.name},
    )
    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "user_registered", "user",
        str(user.id), {"email": user.email, "ip": _get_client_ip(request)}
    )

    return {
        "message": "Registration successful. Please verify your email.",
        "user_id": str(user.id),
    }


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Verify email address with token."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    result = await db.execute(
        select(User).where(
            and_(
                User.email_verification_token == token_hash,
                User.email_verification_expires > datetime.now(timezone.utc),
            )
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires = None
    user.status = "active"
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "email_verified", "user", str(user.id), {}
    )
    return {"message": "Email verified successfully"}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Send password reset email."""
    query = select(User).where(User.email == body.email.lower())
    if body.tenant_id:
        query = query.where(User.tenant_id == body.tenant_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if user and user.status == "active":
        reset_token = secrets.token_urlsafe(32)
        user.password_reset_token = hashlib.sha256(reset_token.encode()).hexdigest()
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()
        background_tasks.add_task(
            send_email,
            to=user.email,
            subject="Reset your password",
            template="reset_password",
            context={"token": reset_token, "user": user.first_name},
        )
        background_tasks.add_task(
            log_action, db, str(user.id), str(user.tenant_id),
            "password_reset_requested", "user", str(user.id), {}
        )

    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Reset password with reset token."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    result = await db.execute(
        select(User).where(
            and_(
                User.password_reset_token == token_hash,
                User.password_reset_expires > datetime.now(timezone.utc),
            )
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user.hashed_password = get_password_hash(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    user.password_changed_at = datetime.now(timezone.utc)
    # Revoke all sessions
    await db.execute(
        update(UserSession)
        .where(and_(UserSession.user_id == user.id, UserSession.revoked == False))
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()

    background_tasks.add_task(
        send_email,
        to=user.email,
        subject="Password changed",
        template="password_changed",
        context={"user": user.first_name},
    )
    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "password_reset", "user", str(user.id), {}
    )
    return {"message": "Password reset successfully"}


@router.post("/magic-link")
async def request_magic_link(
    body: MagicLinkRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Request a magic link for passwordless login."""
    query = select(User).where(
        and_(User.email == body.email.lower(), User.status == "active", User.deleted_at.is_(None))
    )
    if body.tenant_id:
        query = query.where(User.tenant_id == body.tenant_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user:
        token = secrets.token_urlsafe(32)
        redis = await get_redis()
        await redis.setex(
            f"magic_link:{hashlib.sha256(token.encode()).hexdigest()}",
            1800,
            str(user.id),
        )
        background_tasks.add_task(
            send_email,
            to=user.email,
            subject="Your magic login link",
            template="magic_link",
            context={"token": token, "user": user.first_name},
        )
    return {"message": "If the email exists, a magic link has been sent."}


@router.get("/magic-link/verify")
async def verify_magic_link(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Verify magic link and issue tokens."""
    redis = await get_redis()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user_id = await redis.get(f"magic_link:{token_hash}")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired magic link")

    await redis.delete(f"magic_link:{token_hash}")

    result = await db.execute(
        select(User)
        .where(and_(User.id == user_id.decode(), User.deleted_at.is_(None), User.status == "active"))
        .options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "roles": [str(r.id) for r in user.roles],
    }
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate TOTP secret and QR code for MFA setup."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="IGA Platform",
    )

    # Generate QR code
    img = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()

    # Store pending secret in Redis (not yet activated)
    redis = await get_redis()
    await redis.setex(f"mfa_pending:{current_user.id}", 600, secret)

    # Generate backup codes
    backup_codes = [secrets.token_hex(5).upper() for _ in range(10)]

    return MFASetupResponse(
        secret=secret,
        qr_code=f"data:image/png;base64,{qr_b64}",
        backup_codes=backup_codes,
    )


@router.post("/mfa/verify")
async def verify_mfa(
    body: MFAVerifyRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify TOTP code and enable MFA on the account."""
    redis = await get_redis()
    pending_secret = await redis.get(f"mfa_pending:{current_user.id}")

    secret = body.secret or (pending_secret.decode() if pending_secret else None) or current_user.mfa_secret
    if not secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No MFA setup in progress")

    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    current_user.mfa_secret = secret
    current_user.mfa_enabled = True

    # Store backup codes
    await db.execute(
        update(MFABackupCode)
        .where(MFABackupCode.user_id == current_user.id)
        .values(invalidated=True)
    )
    backup_codes = [secrets.token_hex(5).upper() for _ in range(10)]
    for code in backup_codes:
        db.add(MFABackupCode(
            user_id=current_user.id,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
        ))

    await db.commit()
    await redis.delete(f"mfa_pending:{current_user.id}")

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "mfa_enabled", "user", str(current_user.id), {}
    )
    return {"message": "MFA enabled successfully", "backup_codes": backup_codes}


@router.post("/mfa/disable")
async def disable_mfa(
    body: MFADisableRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable MFA. Requires current password and optionally current TOTP code."""
    if not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    if current_user.mfa_enabled and body.code:
        totp = pyotp.TOTP(current_user.mfa_secret)
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    await db.execute(
        update(MFABackupCode)
        .where(MFABackupCode.user_id == current_user.id)
        .values(invalidated=True)
    )
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "mfa_disabled", "user", str(current_user.id), {}
    )
    return {"message": "MFA disabled"}


@router.get("/mfa/backup-codes")
async def list_backup_codes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List backup codes (shows count of remaining active codes, not actual codes)."""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    result = await db.execute(
        select(MFABackupCode).where(
            and_(
                MFABackupCode.user_id == current_user.id,
                MFABackupCode.used == False,
                MFABackupCode.invalidated == False,
            )
        )
    )
    codes = result.scalars().all()
    return {"remaining_count": len(codes)}


@router.post("/mfa/backup-codes/regenerate")
async def regenerate_backup_codes(
    body: MFAVerifyRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate backup codes. Requires current TOTP code."""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")

    totp = pyotp.TOTP(current_user.mfa_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    await db.execute(
        update(MFABackupCode)
        .where(MFABackupCode.user_id == current_user.id)
        .values(invalidated=True)
    )
    backup_codes = [secrets.token_hex(5).upper() for _ in range(10)]
    for code in backup_codes:
        db.add(MFABackupCode(
            user_id=current_user.id,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
        ))
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "backup_codes_regenerated", "user", str(current_user.id), {}
    )
    return {"backup_codes": backup_codes}


@router.post("/oauth/google")
async def oauth_google(
    request: Request,
    body: OAuthRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Google OAuth login."""
    import httpx
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": body.code,
                "client_id": "GOOGLE_CLIENT_ID",
                "client_secret": "GOOGLE_CLIENT_SECRET",
                "redirect_uri": body.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google OAuth failed")

    tokens = token_resp.json()
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Google user info")

    google_user = user_resp.json()
    email = google_user.get("email", "").lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No email from Google")

    result = await db.execute(
        select(User)
        .where(and_(User.email == email, User.deleted_at.is_(None), User.status == "active"))
        .options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found. Please register first.",
        )

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "roles": [str(r.id) for r in user.roles],
    }
    access_token = create_access_token(token_data)
    refresh_token_val = create_refresh_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})

    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "oauth_login", "user",
        str(user.id), {"provider": "google", "ip": _get_client_ip(request)}
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_val,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.post("/oauth/microsoft")
async def oauth_microsoft(
    request: Request,
    body: OAuthRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Microsoft OAuth login."""
    import httpx
    tenant_str = "common"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_str}/oauth2/v2.0/token",
            data={
                "code": body.code,
                "client_id": "MICROSOFT_CLIENT_ID",
                "client_secret": "MICROSOFT_CLIENT_SECRET",
                "redirect_uri": body.redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Microsoft OAuth failed")

    tokens = token_resp.json()
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    if user_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Microsoft user info")

    ms_user = user_resp.json()
    email = (ms_user.get("mail") or ms_user.get("userPrincipalName", "")).lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No email from Microsoft")

    result = await db.execute(
        select(User)
        .where(and_(User.email == email, User.deleted_at.is_(None), User.status == "active"))
        .options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account found")

    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "roles": [str(r.id) for r in user.roles],
    }
    access_token = create_access_token(token_data)
    refresh_token_val = create_refresh_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})

    background_tasks.add_task(
        log_action, db, str(user.id), str(user.tenant_id), "oauth_login", "user",
        str(user.id), {"provider": "microsoft", "ip": _get_client_ip(request)}
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_val,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user profile."""
    result = await db.execute(
        select(User)
        .where(User.id == current_user.id)
        .options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "tenant_id": str(user.tenant_id),
        "status": user.status,
        "mfa_enabled": user.mfa_enabled,
        "email_verified": user.email_verified,
        "roles": [{"id": str(r.id), "name": r.name} for r in user.roles],
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change password. Requires current password."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    current_user.hashed_password = get_password_hash(body.new_password)
    current_user.password_changed_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        send_email,
        to=current_user.email,
        subject="Password changed",
        template="password_changed",
        context={"user": current_user.first_name},
    )
    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "password_changed", "user", str(current_user.id), {}
    )
    return {"message": "Password changed successfully"}


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active sessions for the current user."""
    result = await db.execute(
        select(UserSession).where(
            and_(
                UserSession.user_id == current_user.id,
                UserSession.revoked == False,
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        ).order_by(UserSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return {
        "sessions": [
            {
                "id": str(s.id),
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "device_fingerprint": s.device_fingerprint,
                "created_at": s.created_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
            }
            for s in sessions
        ]
    }


@router.delete("/sessions/{session_id}")
async def terminate_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Terminate a specific session."""
    result = await db.execute(
        select(UserSession).where(
            and_(UserSession.id == session_id, UserSession.user_id == current_user.id)
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    session.revoked = True
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "session_terminated", "session", session_id, {}
    )
    return {"message": "Session terminated"}


@router.delete("/sessions")
async def terminate_all_sessions(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Terminate all sessions except the current one."""
    current_device = _generate_device_fingerprint(request)
    await db.execute(
        update(UserSession)
        .where(
            and_(
                UserSession.user_id == current_user.id,
                UserSession.revoked == False,
                UserSession.device_fingerprint != current_device,
            )
        )
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()

    background_tasks.add_task(
        log_action, db, str(current_user.id), str(current_user.tenant_id),
        "all_sessions_terminated", "user", str(current_user.id), {}
    )
    return {"message": "All other sessions terminated"}
