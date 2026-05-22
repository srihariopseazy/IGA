"""
IGA Platform — FastAPI Application Entry Point
"""
import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import strawberry
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter

from backend.config import settings
from backend.middleware.auth import JWTAuthMiddleware
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.middleware.security import SecurityHeadersMiddleware
from backend.middleware.tenant import TenantMiddleware
from backend.utils.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal GraphQL schema (extend in backend/graphql/ as needed)
# ---------------------------------------------------------------------------

@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "ok"


graphql_schema = strawberry.Schema(query=Query)
graphql_router = GraphQLRouter(graphql_schema)


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle hooks."""
    logger.info("Starting IGA Platform v%s [%s]", settings.APP_VERSION, settings.ENVIRONMENT)

    # Initialize database tables
    try:
        from backend.database import init_db
        await init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.error("Database initialization failed: %s", exc)

    # Warm up Redis connection
    try:
        from backend.utils.redis_client import redis_client
        await redis_client.set("startup_ping", "1", expire=5)
        logger.info("Redis connection established")
    except Exception as exc:
        logger.warning("Redis connection failed (non-fatal): %s", exc)

    # Initialize OpenTelemetry tracing
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            resource = Resource(attributes={"service.name": settings.OTEL_SERVICE_NAME})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
            logger.info("OpenTelemetry tracing initialized → %s", settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        except ImportError:
            logger.warning("OpenTelemetry packages not installed; tracing disabled")
        except Exception as exc:
            logger.warning("OpenTelemetry setup failed: %s", exc)

    # Start WebSocket ping loop
    async def ws_ping_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await ws_manager.ping_all()
            except Exception as exc:
                logger.debug("WS ping error: %s", exc)

    ping_task = asyncio.create_task(ws_ping_loop())

    yield  # Application runs here

    # Shutdown
    ping_task.cancel()
    try:
        await ping_task
    except asyncio.CancelledError:
        pass

    try:
        from backend.utils.redis_client import redis_client
        await redis_client.close()
    except Exception:
        pass

    try:
        from backend.database import engine
        await engine.dispose()
    except Exception:
        pass

    logger.info("IGA Platform shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Enterprise Identity Governance & Administration Platform",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware (added in reverse order — last added = outermost)
    # ------------------------------------------------------------------

    # Security headers (outermost so every response gets them)
    app.add_middleware(SecurityHeadersMiddleware)

    # Tenant isolation
    app.add_middleware(TenantMiddleware)

    # JWT authentication
    app.add_middleware(JWTAuthMiddleware)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # Trusted hosts (restrict in production)
    if not settings.DEBUG:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"],  # Tighten to specific domains in production
        )

    # Request timing middleware (inline)
    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        return response

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    _register_routers(app)

    # GraphQL
    app.include_router(graphql_router, prefix="/graphql")

    # ------------------------------------------------------------------
    # WebSocket endpoint
    # ------------------------------------------------------------------
    @app.websocket("/ws/{tenant_id}/{user_id}")
    async def websocket_endpoint(websocket: WebSocket, tenant_id: str, user_id: str):
        """Real-time notifications channel per tenant/user."""
        await ws_manager.connect(websocket, tenant_id, user_id)
        try:
            while True:
                data = await websocket.receive_text()
                # Echo back pong on ping
                import json
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await ws_manager.send_personal_message(
                            {"type": "pong", "timestamp": msg.get("timestamp")},
                            tenant_id,
                            user_id,
                        )
                except Exception:
                    pass
        except WebSocketDisconnect:
            await ws_manager.disconnect(tenant_id, user_id)

    # ------------------------------------------------------------------
    # Global exception handlers
    # ------------------------------------------------------------------
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": f"Resource not found: {request.url.path}",
                "error_code": "NOT_FOUND",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc):
        return JSONResponse(
            status_code=405,
            content={
                "success": False,
                "error": "Method not allowed",
                "error_code": "METHOD_NOT_ALLOWED",
            },
        )

    @app.exception_handler(422)
    async def validation_error_handler(request: Request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "Validation error",
                "error_code": "VALIDATION_ERROR",
                "details": exc.errors() if hasattr(exc, "errors") else str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error(
            "Unhandled exception [request_id=%s] %s %s: %s",
            request_id,
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error",
                "error_code": "INTERNAL_SERVER_ERROR",
                "request_id": request_id,
            },
        )

    # ------------------------------------------------------------------
    # Health endpoint
    # ------------------------------------------------------------------
    @app.get("/health", tags=["health"], include_in_schema=True)
    async def health_check():
        """System health status check."""
        status: Dict[str, Any] = {
            "status": "healthy",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "services": {},
        }

        # Redis check
        try:
            from backend.utils.redis_client import redis_client
            await redis_client.set("health_check", "1", expire=5)
            status["services"]["redis"] = "up"
        except Exception as exc:
            status["services"]["redis"] = f"down: {exc}"
            status["status"] = "degraded"

        # Database check
        try:
            from backend.database import AsyncSessionLocal
            from sqlalchemy import text
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            status["services"]["database"] = "up"
        except Exception as exc:
            status["services"]["database"] = f"down: {exc}"
            status["status"] = "degraded"

        # WebSocket connections info
        status["services"]["websocket"] = {
            "active_connections": ws_manager.connection_count()
        }

        http_status = 200 if status["status"] == "healthy" else 503
        return JSONResponse(content=status, status_code=http_status)

    # ------------------------------------------------------------------
    # Prometheus metrics
    # ------------------------------------------------------------------
    if settings.PROMETHEUS_ENABLED:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator
            Instrumentator(
                should_group_status_codes=True,
                should_ignore_untemplated=True,
                should_respect_env_var=True,
                should_instrument_requests_inprogress=True,
                excluded_handlers=["/health", "/metrics"],
            ).instrument(app).expose(app, endpoint="/metrics")
            logger.info("Prometheus metrics exposed at /metrics")
        except ImportError:
            logger.warning("prometheus_fastapi_instrumentator not installed; metrics disabled")

    return app


def _register_routers(app: FastAPI) -> None:
    """Import and mount all API routers. Missing router modules are skipped gracefully."""
    prefix = settings.API_V1_PREFIX

    router_configs = [
        # Routes WITHOUT their own prefix — main.py provides the path suffix
        ("backend.routes.auth", "/auth", ["auth"]),
        ("backend.routes.roles", "", ["roles"]),
        ("backend.routes.health", "/health", ["health"]),
        ("backend.routes.dashboard", "/dashboard", ["dashboard"]),
        # Routes WITH their own prefix — use "" so the router's own prefix is used
        ("backend.routes.users", "", ["users"]),
        ("backend.routes.permissions", "", ["permissions"]),
        ("backend.routes.departments", "", ["departments"]),
        ("backend.routes.applications", "", ["applications"]),
        ("backend.routes.entitlements", "", ["entitlements"]),
        ("backend.routes.access_requests", "", ["access-requests"]),
        ("backend.routes.approvals", "", ["approvals"]),
        ("backend.routes.sync_jobs", "", ["sync-jobs"]),
        ("backend.routes.config", "", ["config"]),
        ("backend.routes.workflows", "", ["workflows"]),
        ("backend.routes.certifications", "", ["certifications"]),
        ("backend.routes.sod", "", ["sod"]),
        ("backend.routes.provisioning", "", ["provisioning"]),
        ("backend.routes.connectors", "", ["connectors"]),
        ("backend.routes.audit", "", ["audit"]),
        ("backend.routes.compliance", "", ["compliance"]),
        ("backend.routes.risk", "", ["risk"]),
        ("backend.routes.pam", "", ["pam"]),
        ("backend.routes.notifications", "", ["notifications"]),
        ("backend.routes.tenants", "", ["tenants"]),
    ]

    for module_path, path_suffix, tags in router_configs:
        try:
            import importlib
            module = importlib.import_module(module_path)
            router = getattr(module, "router", None)
            if router is not None:
                app.include_router(router, prefix=f"{prefix}{path_suffix}", tags=tags)
                logger.debug("Registered router: %s%s", prefix, path_suffix)
            else:
                logger.warning("Module %s has no 'router' attribute", module_path)
        except ImportError:
            logger.warning("Router module not found (skipping): %s", module_path)
        except Exception as exc:
            logger.error("Failed to register router %s: %s", module_path, exc)

    # SCIM v2 router (separate prefix)
    try:
        import importlib
        scim_module = importlib.import_module("backend.routes.scim")
        scim_router = getattr(scim_module, "router", None)
        if scim_router:
            app.include_router(scim_router, prefix="/scim/v2", tags=["scim"])
    except ImportError:
        logger.warning("SCIM router module not found (skipping)")
    except Exception as exc:
        logger.error("Failed to register SCIM router: %s", exc)


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
app = create_app()
