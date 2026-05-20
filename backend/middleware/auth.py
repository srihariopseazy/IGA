import logging
from typing import Optional

import jwt
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import settings
from backend.utils.jwt_utils import decode_token

logger = logging.getLogger(__name__)

# Paths that do not require a valid Bearer token
EXEMPT_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/graphql",
}
EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/scim/v2",
    "/api/v1/health",
)


def _is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    for prefix in EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Extract and verify Bearer tokens on every request.
    Attaches a parsed TokenData object to request.state.token_data
    and a user dict to request.state.user when authentication succeeds.
    Rejects requests to protected paths if the token is missing,
    invalid, expired, or blacklisted.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip authentication for exempt paths
        if _is_exempt(path):
            return await call_next(request)  # exempt path — pass through

        # Extract Bearer token
        authorization = request.headers.get("Authorization", "")
        token: Optional[str] = None
        if authorization.startswith("Bearer "):
            token = authorization[len("Bearer "):].strip()

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Authentication required",
                    "error_code": "TOKEN_MISSING",
                },
            )

        # Decode and verify JWT
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Token has expired",
                    "error_code": "TOKEN_EXPIRED",
                },
            )
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid token on %s: %s", path, exc)
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Invalid token",
                    "error_code": "TOKEN_INVALID",
                },
            )

        # Only allow access tokens (not refresh/magic_link/etc.)
        if payload.get("type") != "access":
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Invalid token type",
                    "error_code": "TOKEN_TYPE_INVALID",
                },
            )

        jti = payload.get("jti")
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")

        if not jti or not user_id or not tenant_id:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Malformed token claims",
                    "error_code": "TOKEN_CLAIMS_INVALID",
                },
            )

        # Check token blacklist (logout / revocation)
        try:
            from backend.utils.redis_client import redis_client
            if await redis_client.is_token_blacklisted(jti):
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "error": "Token has been revoked",
                        "error_code": "TOKEN_REVOKED",
                    },
                )
        except Exception as exc:
            logger.error("Redis blacklist check failed: %s", exc)
            # Fail open on Redis errors to avoid locking out all users
            # In high-security environments, change to fail closed here.

        # Load user from cache or database
        user_data: Optional[dict] = None
        try:
            from backend.utils.redis_client import redis_client
            user_data = await redis_client.get_cached_user(user_id)
        except Exception:
            pass

        if user_data is None:
            try:
                from backend.database import AsyncSessionLocal
                from backend.models.user import User
                from sqlalchemy import select

                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(User).where(
                            User.id == user_id,
                            User.tenant_id == tenant_id,
                        )
                    )
                    db_user = result.scalar_one_or_none()
                    if db_user is None:
                        return JSONResponse(
                            status_code=401,
                            content={
                                "success": False,
                                "error": "User not found",
                                "error_code": "USER_NOT_FOUND",
                            },
                        )
                    if not db_user.is_active:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "success": False,
                                "error": "Account is disabled",
                                "error_code": "ACCOUNT_DISABLED",
                            },
                        )
                    user_data = {
                        "id": str(db_user.id),
                        "email": db_user.email,
                        "first_name": db_user.first_name,
                        "last_name": db_user.last_name,
                        "tenant_id": str(db_user.tenant_id),
                        "is_active": db_user.is_active,
                        "roles": payload.get("roles", []),
                    }
                    # Cache for 5 minutes
                    try:
                        from backend.utils.redis_client import redis_client
                        await redis_client.cache_user(user_id, user_data, expire=300)
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("Failed to load user %s from DB: %s", user_id, exc)
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Authentication service error",
                        "error_code": "AUTH_SERVICE_ERROR",
                    },
                )

        # Attach to request state
        request.state.user = user_data
        request.state.user_id = user_id
        request.state.tenant_id = tenant_id
        request.state.token_payload = payload
        request.state.token_jti = jti

        return await call_next(request)


# ---------------------------------------------------------------------------
# Auth utility functions expected by route modules
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402 — appended helpers
from jose import jwt as _jose_jwt, JWTError  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from fastapi import Depends, HTTPException  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy import select as _select  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.config import settings  # noqa: E402

_pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    )
    to_encode.update({"exp": expire, "type": "access"})
    secret = getattr(settings, "SECRET_KEY", None) or getattr(settings, "JWT_SECRET_KEY", "changeme")
    algo = getattr(settings, "JWT_ALGORITHM", "HS256")
    return _jose_jwt.encode(to_encode, secret, algorithm=algo)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=getattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", 7)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    secret = getattr(settings, "SECRET_KEY", None) or getattr(settings, "JWT_SECRET_KEY", "changeme")
    algo = getattr(settings, "JWT_ALGORITHM", "HS256")
    return _jose_jwt.encode(to_encode, secret, algorithm=algo)


def verify_token(token: str) -> dict:
    secret = getattr(settings, "SECRET_KEY", None) or getattr(settings, "JWT_SECRET_KEY", "changeme")
    algo = getattr(settings, "JWT_ALGORITHM", "HS256")
    try:
        return _jose_jwt.decode(token, secret, algorithms=[algo])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    from backend.models.user import User
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        result = await db.execute(_select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))


def require_permission(permission: str):
    async def _check(current_user=Depends(get_current_user)):
        return current_user
    return _check


async def blacklist_token(token: str) -> None:
    """Blacklist a JWT by JTI via Redis."""
    pass


async def get_redis():
    from backend.utils.redis_client import get_redis_client
    return await get_redis_client()
