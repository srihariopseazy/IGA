import logging
import time
from typing import Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import settings

logger = logging.getLogger(__name__)

# Endpoint tier classification
AUTH_PREFIXES = ("/api/v1/auth/",)
ADMIN_PREFIXES = ("/api/v1/tenants/",)
SCIM_PREFIXES = ("/scim/v2",)
# Everything else is "standard"

# Limits: (requests, window_seconds)
AUTH_LIMIT = (10, 60)
STANDARD_LIMIT = (60, 60)
ADMIN_LIMIT = (30, 60)
SCIM_LIMIT = (100, 60)

EXEMPT_PATHS = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _get_tier(path: str) -> Tuple[int, int]:
    """Return (max_requests, window_seconds) for the given path."""
    for prefix in AUTH_PREFIXES:
        if path.startswith(prefix):
            return AUTH_LIMIT
    for prefix in SCIM_PREFIXES:
        if path.startswith(prefix):
            return SCIM_LIMIT
    for prefix in ADMIN_PREFIXES:
        if path.startswith(prefix):
            return ADMIN_LIMIT
    return STANDARD_LIMIT


def _get_client_key(request: Request) -> str:
    """
    Return a rate-limit key:
    - For authenticated requests: 'rl:user:{user_id}'
    - For anonymous requests:     'rl:ip:{ip}'
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"rl:user:{user_id}"
    # Get real IP from X-Forwarded-For or fall back to client host
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"rl:ip:{ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter backed by Redis.

    Uses a Redis key per (client, endpoint-tier) with a TTL equal to the
    window size. On each request:
    1. Increment the counter with INCR (atomic).
    2. Set the TTL on the first hit in the window.
    3. If counter > limit, return 429 with Retry-After header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in EXEMPT_PATHS:
            return await call_next(request)

        max_requests, window = _get_tier(path)
        client_key = _get_client_key(request)
        tier_label = (
            "auth" if any(path.startswith(p) for p in AUTH_PREFIXES)
            else "scim" if any(path.startswith(p) for p in SCIM_PREFIXES)
            else "admin" if any(path.startswith(p) for p in ADMIN_PREFIXES)
            else "standard"
        )
        redis_key = f"{client_key}:{tier_label}"

        try:
            from backend.utils.redis_client import redis_client

            count = await redis_client.incr(redis_key)
            if count == 1:
                # First request in this window — set TTL
                await redis_client.expire(redis_key, window)

            ttl = await redis_client.ttl(redis_key)
            retry_after = max(ttl, 1)

            # Add rate-limit headers to all responses
            response_headers = {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(max(0, max_requests - count)),
                "X-RateLimit-Reset": str(int(time.time()) + retry_after),
            }

            if count > max_requests:
                logger.warning(
                    "Rate limit exceeded: key=%s count=%d limit=%d",
                    redis_key, count, max_requests,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Rate limit exceeded. Please slow down.",
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "retry_after": retry_after,
                    },
                    headers={
                        **response_headers,
                        "Retry-After": str(retry_after),
                    },
                )

            response = await call_next(request)
            for header, value in response_headers.items():
                response.headers[header] = value
            return response

        except Exception as exc:
            # On Redis failure, fail open (allow the request)
            logger.error("Rate limiter Redis error: %s", exc)
            return await call_next(request)
