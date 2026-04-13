"""Hinweisgebersystem – FastAPI Application Entry Point.

This module creates and configures the FastAPI application including:
- CORS middleware (must be added before routes)
- Custom middleware (tenant, audit, rate limit, anonymity)
- Structured logging with structlog
- Health-check endpoint used by Caddy reverse proxy
- Lifespan management for startup/shutdown of shared resources
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.database import (
    dispose_admin_engine,
    dispose_engine,
    init_admin_engine,
    init_engine,
)
from app.core.storage import dispose_storage, init_storage
from app.tasks import shutdown_scheduler, start_scheduler

logger = structlog.get_logger(__name__)


# ── Lifespan ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of shared resources.

    Startup: initialise database engine, Redis pool, MinIO client, scheduler.
    Shutdown: dispose engine, close pools, shut down scheduler.
    """
    settings = get_settings()
    logger.info("application_startup")

    # 1. Database engine (app_user for RLS enforcement)
    init_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_recycle=settings.db_pool_recycle,
    )

    # 2. Admin database engine (superuser, bypasses RLS for cross-tenant lookups)
    init_admin_engine(settings.database_admin_url)

    # 3. MinIO storage client
    await init_storage()

    # 4. Background task scheduler (deadline checker, data retention, email worker)
    start_scheduler()

    yield

    logger.info("application_shutdown")

    # Shut down scheduler (wait for running jobs)
    shutdown_scheduler()

    # Dispose storage client
    await dispose_storage()

    # Dispose admin database engine
    await dispose_admin_engine()

    # Dispose database engine
    await dispose_engine()


# ── Application factory ────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    application = FastAPI(
        title="Hinweisgebersystem API",
        description="Whistleblower reporting portal API (HinSchG / LkSG)",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    _configure_middleware(application)
    _include_routers(application)

    return application


# ── Middleware configuration ────────────────────────────────
# IMPORTANT: CORS middleware MUST be added before routes are
# registered so that preflight OPTIONS requests are handled.
# Starlette middleware execution order is LIFO (last added runs
# first), so the outermost middleware must be added last.


def _configure_middleware(application: FastAPI) -> None:
    """Register all middleware in the correct order.

    Starlette processes middleware in reverse registration order (LIFO).
    The desired execution order from outermost to innermost is:

    1. TrustedHost – reject requests with unexpected Host headers
    2. CORS – handle preflight and response headers
    3. AntiForensicsMiddleware – add security headers to ALL responses
    4. AnonymityMiddleware – strip IPs, pad response times for reporters
    5. RateLimiterMiddleware – Redis-based sliding window rate limits
    6. TenantResolverMiddleware – resolve tenant from request
    7. AuditLoggerMiddleware – log state-changing requests

    We register them in reverse order so the execution wraps correctly.
    """
    settings = get_settings()

    # Determine CORS origins from configuration
    cors_origins = settings.cors_origins_list if settings.cors_origins else ["*"]

    # 7. AuditLoggerMiddleware (innermost – runs last)
    from app.middleware.audit_logger import AuditLoggerMiddleware
    application.add_middleware(AuditLoggerMiddleware)

    # 6. TenantResolverMiddleware
    from app.middleware.tenant_resolver import TenantResolverMiddleware
    application.add_middleware(TenantResolverMiddleware)

    # 5. RateLimiterMiddleware
    from app.middleware.rate_limiter import RateLimiterMiddleware
    application.add_middleware(RateLimiterMiddleware)

    # 4. AnonymityMiddleware
    from app.middleware.anonymity import AnonymityMiddleware
    application.add_middleware(AnonymityMiddleware)

    # 3. AntiForensicsMiddleware
    from app.middleware.anonymity import AntiForensicsMiddleware
    application.add_middleware(AntiForensicsMiddleware)

    # 2. CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Content-Disposition"],
    )

    # 1. TrustedHost (outermost – runs first)
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )


# ── Router registration ────────────────────────────────────


def _include_routers(application: FastAPI) -> None:
    """Include all API v1 routers.

    Routers will be added incrementally as API endpoint subtasks
    are implemented. Each router module uses APIRouter with its
    own prefix and tags (see pattern: fastapi_router).
    """

    # Health-check is always available, even before other routers.
    @application.get(
        "/api/v1/health",
        tags=["health"],
        summary="Health check",
    )
    async def health_check() -> dict:
        """Liveness probe used by Caddy proxy health check."""
        return {"status": "ok"}

    # API v1 aggregated router (auth, reports, admin, etc.)
    from app.api.v1 import router as api_v1_router  # noqa: PLC0415

    application.include_router(api_v1_router)


# ── Module-level app instance (used by uvicorn) ────────────

app = create_app()
