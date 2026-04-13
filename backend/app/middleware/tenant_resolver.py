"""Hinweisgebersystem -- Tenant Resolver Middleware.

Extracts the current tenant from the incoming request and makes the
tenant UUID available to the rest of the request lifecycle via:

- ``request.state.tenant_id`` (``UUID | None``) -- for FastAPI deps
- ``_tenant_id_ctx`` context variable -- for non-request code paths
- ``get_current_tenant()`` FastAPI dependency -- returns the UUID
- ``get_tenant_db()`` convenience dependency -- yields an RLS-scoped
  database session with ``SET LOCAL app.current_tenant_id`` applied

Resolution order:

1. ``X-Tenant-Slug`` header (development / testing override)
2. Subdomain from ``Host`` header (production)
3. Path prefix ``/t/{slug}/...`` (development fallback)

The resolved tenant UUID is used downstream by ``get_db()`` to execute
``SET LOCAL app.current_tenant_id`` for PostgreSQL Row-Level Security.

RLS context flow:

1. Middleware resolves tenant slug from the request.
2. Slug is looked up in the database (with in-memory cache).
3. UUID is stored in ``request.state.tenant_id``.
4. ``get_tenant_db()`` reads the UUID and passes it to ``get_db()``,
   which executes ``SET LOCAL`` for the current transaction.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
from uuid import UUID

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# ── Context variable ──────────────────────────────────────────
# Accessible from anywhere within the same async task.

_tenant_id_ctx: ContextVar[UUID | None] = ContextVar(
    "tenant_id", default=None
)

# ── In-memory tenant cache ────────────────────────────────────
# Maps slug -> (tenant_id, is_active, cached_at_monotonic).
# Populated lazily on first lookup; refreshed after TTL expiry.

_tenant_cache: dict[str, tuple[UUID, bool, float]] = {}
_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes

# ── Exempt paths (no tenant context required) ─────────────────

_TENANT_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
)


def _is_exempt(path: str) -> bool:
    """Return ``True`` if *path* does not require tenant context."""
    return any(path.startswith(prefix) for prefix in _TENANT_EXEMPT_PREFIXES)


# ── Tenant lookup with caching ────────────────────────────────


async def _lookup_tenant(slug: str) -> tuple[UUID, bool] | None:
    """Look up a tenant by slug, returning ``(id, is_active)`` or *None*.

    Results are cached in ``_tenant_cache`` for ``_CACHE_TTL_SECONDS``
    to avoid a database round-trip on every request.
    """
    now = time.monotonic()

    # Fast-path: cache hit
    cached = _tenant_cache.get(slug)
    if cached is not None:
        tenant_id, is_active, cached_at = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return tenant_id, is_active

    # Cache miss -- query the database
    try:
        from sqlalchemy import select

        from app.core.database import get_session_factory
        from app.models.tenant import Tenant

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Tenant.id, Tenant.is_active).where(
                    Tenant.slug == slug
                )
            )
            row = result.first()
            if row is not None:
                _tenant_cache[slug] = (row.id, row.is_active, now)
                return row.id, row.is_active
    except RuntimeError:
        # Database engine not initialised yet (e.g. during startup)
        logger.warning("tenant_lookup_skipped_db_not_ready", slug=slug)
    except Exception:
        logger.exception("tenant_lookup_failed", slug=slug)

    return None


# ── Slug extraction helpers ───────────────────────────────────


def _extract_slug_from_host(host: str) -> str | None:
    """Extract tenant slug from the subdomain portion of the *Host* header.

    Examples::

        acme.hinweis.example.com  ->  "acme"
        hinweis.example.com       ->  None  (base domain, no subdomain)
        localhost:8000            ->  None
    """
    hostname = host.split(":")[0]
    parts = hostname.split(".")
    # Need at least 3 parts for a genuine subdomain (slug.domain.tld).
    # Skip common non-tenant prefixes.
    if len(parts) >= 3 and parts[0] not in ("www", "localhost", "api"):
        return parts[0]
    return None


def _extract_slug_from_path(path: str) -> tuple[str | None, str]:
    """Extract tenant slug from a ``/t/{slug}/...`` path prefix.

    Returns ``(slug, remaining_path)`` if the prefix is present,
    otherwise ``(None, original_path)``.

    Examples::

        /t/acme/api/v1/reports  ->  ("acme", "/api/v1/reports")
        /api/v1/reports         ->  (None,   "/api/v1/reports")
    """
    if path.startswith("/t/"):
        rest = path[3:]  # strip "/t/"
        slash_idx = rest.find("/")
        if slash_idx > 0:
            return rest[:slash_idx], rest[slash_idx:]
        if rest:
            return rest, "/"
    return None, path


# ── Middleware ─────────────────────────────────────────────────


class TenantResolverMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that resolves the current tenant for each request.

    Resolution order:

    1. ``X-Tenant-Slug`` request header (development / testing)
    2. Subdomain extracted from the ``Host`` header (production)
    3. Path prefix ``/t/{slug}/...`` (development fallback -- the
       prefix is stripped so downstream routes see the canonical path)

    The resolved ``tenant_id`` (UUID) is stored in:

    - ``request.state.tenant_id``
    - ``request.state.tenant_slug``
    - The ``_tenant_id_ctx`` context variable

    Inactive tenants receive a ``403 Forbidden`` response.
    Unknown slugs receive a ``404 Not Found`` response (information
    hiding -- we never reveal whether a tenant *exists* but is
    inactive vs. does not exist at all).
    """

    async def dispatch(
        self, request: Request, call_next: ...,
    ) -> Response:
        """Resolve tenant and forward the request."""
        token = _tenant_id_ctx.set(None)

        try:
            path = request.url.path

            # ── Exempt paths (health, docs) ──────────────────
            if _is_exempt(path):
                request.state.tenant_id = None
                request.state.tenant_slug = None
                return await call_next(request)

            # ── 1. Header override (dev only) ────────────────
            from app.core.config import get_settings as _get_settings
            _settings = _get_settings()
            slug: str | None = None
            if getattr(_settings, "debug", False):
                slug = request.headers.get("x-tenant-slug")

            # ── 2. Subdomain ─────────────────────────────────
            if not slug:
                host = request.headers.get("host", "")
                slug = _extract_slug_from_host(host)

            # ── 3. Path prefix (/t/{slug}/...) ───────────────
            if not slug:
                slug, stripped_path = _extract_slug_from_path(path)
                if slug:
                    # Rewrite scope path so routers see canonical URL
                    request.scope["path"] = stripped_path

            # ── No slug resolved ─────────────────────────────
            if not slug:
                # Allow the request through without tenant context.
                # Endpoints that *require* a tenant will fail via
                # the ``get_current_tenant()`` dependency.
                request.state.tenant_id = None
                request.state.tenant_slug = None
                return await call_next(request)

            # ── Look up tenant ───────────────────────────────
            result = await _lookup_tenant(slug)

            if result is None:
                # Information hiding: always 404 regardless of reason
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Tenant not found"},
                )

            tenant_id, is_active = result

            if not is_active:
                # Information hiding: return 404 for inactive tenants too
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Tenant not found"},
                )

            # ── Store tenant context ─────────────────────────
            request.state.tenant_id = tenant_id
            request.state.tenant_slug = slug
            _tenant_id_ctx.set(tenant_id)

            logger.debug(
                "tenant_resolved",
                tenant_slug=slug,
                tenant_id=str(tenant_id),
            )

            return await call_next(request)

        finally:
            _tenant_id_ctx.reset(token)


# ── FastAPI dependencies ──────────────────────────────────────


async def get_current_tenant(request: Request) -> UUID:
    """FastAPI dependency that returns the resolved tenant UUID.

    Reads from ``request.state.tenant_id`` which is set by
    ``TenantResolverMiddleware``.  Raises ``400 Bad Request`` if no
    tenant was resolved (i.e. the request did not carry a tenant slug).

    Usage::

        from app.middleware.tenant_resolver import get_current_tenant

        @router.get("/items")
        async def list_items(
            tenant_id: UUID = Depends(get_current_tenant),
        ):
            ...
    """
    tenant_id: UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required but not resolved from request",
        )
    return tenant_id


async def get_current_tenant_optional(
    request: Request,
) -> UUID | None:
    """Like ``get_current_tenant`` but returns ``None`` instead of 400.

    Use for endpoints that can operate with *or* without a tenant
    context (e.g. super-admin / system-level endpoints).
    """
    return getattr(request.state, "tenant_id", None)


async def get_tenant_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Convenience dependency: RLS-scoped database session.

    Combines tenant resolution (from request state) with database
    session creation.  The session has ``SET LOCAL app.current_tenant_id``
    applied so that all queries are automatically filtered by RLS.

    Usage::

        from app.middleware.tenant_resolver import get_tenant_db

        @router.get("/items")
        async def list_items(
            db: AsyncSession = Depends(get_tenant_db),
        ):
            result = await db.execute(select(Item))
            return result.scalars().all()
    """
    from app.core.database import get_db

    tenant_id: UUID | None = getattr(request.state, "tenant_id", None)
    async for session in get_db(tenant_id=tenant_id):
        yield session


# ── Utility functions ─────────────────────────────────────────


def get_tenant_id_from_context() -> UUID | None:
    """Read the current tenant ID from the context variable.

    Useful for code executing within the same async task but outside
    the FastAPI dependency-injection scope (e.g. event callbacks,
    background tasks spawned from a request).
    """
    return _tenant_id_ctx.get()


def clear_tenant_cache() -> None:
    """Clear the entire in-memory tenant cache.

    Call after bulk tenant changes or during integration tests.
    """
    _tenant_cache.clear()


def invalidate_tenant_cache(slug: str) -> None:
    """Remove a single tenant from the cache by slug.

    Call after a tenant is updated or deactivated.
    """
    _tenant_cache.pop(slug, None)
