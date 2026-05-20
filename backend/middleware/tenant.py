import logging
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

EXEMPT_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}
EXEMPT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/health",
)


def _is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    for prefix in EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _extract_tenant_from_subdomain(host: str) -> Optional[str]:
    """Extract tenant slug from subdomain, e.g. 'acme.iga.example.com' → 'acme'."""
    parts = host.split(".")
    if len(parts) >= 3:
        return parts[0]
    return None


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolve and validate the current tenant for every request.

    Tenant resolution order:
    1. JWT claim (request.state.token_payload["tenant_id"]) — set by JWTAuthMiddleware
    2. X-Tenant-ID request header
    3. Subdomain of the Host header

    After resolution the middleware:
    - Verifies the tenant exists and is active in the database
    - Blocks suspended/deleted tenants with 403
    - Attaches the tenant object to request.state.tenant
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if _is_exempt(path):
            return await call_next(request)

        tenant_id: Optional[str] = None

        # 1. From JWT claims (already attached by JWTAuthMiddleware)
        token_payload = getattr(request.state, "token_payload", None)
        if token_payload:
            tenant_id = token_payload.get("tenant_id")

        # 2. From X-Tenant-ID header
        if not tenant_id:
            tenant_id = request.headers.get("X-Tenant-ID")

        # 3. From subdomain
        if not tenant_id:
            host = request.headers.get("host", "")
            tenant_id = _extract_tenant_from_subdomain(host)

        if not tenant_id:
            # Some routes (e.g. /scim/v2) may embed tenant in the path
            # or rely on header-only resolution; skip enforcement here
            return await call_next(request)

        # Validate tenant against DB (with caching)
        tenant_data: Optional[dict] = None
        try:
            from backend.utils.redis_client import redis_client
            cached = await redis_client.get(f"tenant:{tenant_id}")
            if cached:
                import json
                tenant_data = json.loads(cached)
        except Exception as exc:
            logger.debug("Tenant cache lookup failed: %s", exc)

        if tenant_data is None:
            try:
                from backend.database import AsyncSessionLocal
                from backend.models.tenant import Tenant
                from sqlalchemy import select

                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Tenant).where(Tenant.id == tenant_id)
                    )
                    tenant = result.scalar_one_or_none()

                    if tenant is None:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "success": False,
                                "error": "Tenant not found",
                                "error_code": "TENANT_NOT_FOUND",
                            },
                        )

                    status = getattr(tenant, "status", "active")
                    if status == "suspended":
                        return JSONResponse(
                            status_code=403,
                            content={
                                "success": False,
                                "error": "Tenant account is suspended",
                                "error_code": "TENANT_SUSPENDED",
                            },
                        )

                    if status == "deleted" or getattr(tenant, "deleted_at", None) is not None:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "success": False,
                                "error": "Tenant not found",
                                "error_code": "TENANT_NOT_FOUND",
                            },
                        )

                    tenant_data = {
                        "id": str(tenant.id),
                        "name": getattr(tenant, "name", ""),
                        "slug": getattr(tenant, "slug", ""),
                        "status": status,
                        "plan": getattr(tenant, "plan", "free"),
                    }

                    # Cache tenant for 10 minutes
                    try:
                        import json
                        from backend.utils.redis_client import redis_client
                        await redis_client.set(
                            f"tenant:{tenant_id}",
                            json.dumps(tenant_data),
                            expire=600,
                        )
                    except Exception:
                        pass

            except Exception as exc:
                logger.error("Tenant validation error for %s: %s", tenant_id, exc)
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Tenant validation service error",
                        "error_code": "TENANT_SERVICE_ERROR",
                    },
                )

        # Attach tenant to request state
        request.state.tenant = tenant_data
        request.state.tenant_id = tenant_data["id"]

        return await call_next(request)
