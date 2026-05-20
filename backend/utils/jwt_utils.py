from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import uuid
import jwt
from backend.config import settings


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a signed JWT access token.
    data should include: sub (user_id), tenant_id, email, roles
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    jti = str(uuid.uuid4())
    to_encode.update({
        "iat": now,
        "exp": expire,
        "jti": jti,
        "type": "access",
    })
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def create_refresh_token(user_id: str, tenant_id: str, jti: str) -> str:
    """
    Create a refresh token tied to a specific access token jti.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "access_jti": jti,
        "jti": refresh_jti,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and verify a JWT token.
    Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError on failure.
    """
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return payload


def create_magic_link_token(email: str, tenant_id: str) -> str:
    """
    Create a short-lived token for magic link authentication.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.MAGIC_LINK_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    payload = {
        "sub": email,
        "tenant_id": tenant_id,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "magic_link",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_email_verification_token(user_id: str, email: str) -> str:
    """
    Create a token for email verification (24-hour expiry).
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=24)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "email_verification",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_password_reset_token(user_id: str, email: str) -> str:
    """
    Create a short-lived password reset token (15-minute expiry).
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=15)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "password_reset",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
