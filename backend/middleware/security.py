import uuid
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self';"
)

PERMISSIONS_POLICY = (
    "accelerometer=(), "
    "camera=(), "
    "geolocation=(), "
    "gyroscope=(), "
    "magnetometer=(), "
    "microphone=(), "
    "payment=(), "
    "usb=()"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Attach security-related HTTP response headers to every response.
    Also generates and propagates a unique X-Request-ID for tracing.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Propagate or generate a request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response: Response = await call_next(request)

        # --- Security headers ---

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # HSTS: enforce HTTPS for 1 year, including subdomains
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # Content Security Policy
        response.headers["Content-Security-Policy"] = CSP_POLICY

        # Referrer policy: don't leak full URL to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Feature/Permissions Policy
        response.headers["Permissions-Policy"] = PERMISSIONS_POLICY

        # Remove potentially revealing headers
        response.headers["Server"] = ""
        if "X-Powered-By" in response.headers: del response.headers["X-Powered-By"]

        # XSS protection header (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Cache-Control for API responses (prevent sensitive data caching)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault(
                "Cache-Control", "no-store, no-cache, must-revalidate, private"
            )
            response.headers.setdefault("Pragma", "no-cache")

        # Propagate request ID in response
        response.headers["X-Request-ID"] = request_id

        return response
