"""Hinweisgebersystem -- Audit Logger Middleware.

Automatically records an append-only audit trail for every
state-changing HTTP request (POST, PUT, PATCH, DELETE).  Each entry
captures:

- **action**: Derived from HTTP method + path (e.g. ``case.created``).
- **actor**: The authenticated user (UUID) or ``"system"``/``"reporter"``.
- **resource**: The type and ID of the affected resource (extracted from
  the URL path).
- **details**: A JSONB object with request-specific data.  For mutation
  endpoints the response body may contain old/new values that services
  inject via ``request.state.audit_details``.
- **timestamp**: Server-side ``datetime.now(UTC)``.

The middleware writes directly to the ``audit_logs`` table via
SQLAlchemy.  Because the audit log is append-only (immutable), we use a
short-lived session that commits immediately and never updates or
deletes rows.

Services can enrich the audit entry by setting attributes on
``request.state`` before the response is returned:

- ``request.state.audit_action``  -- override the auto-detected action
- ``request.state.audit_details`` -- dict with old/new values, reasons
- ``request.state.audit_resource_type`` -- override resource type
- ``request.state.audit_resource_id``   -- override resource ID
- ``request.state.audit_skip``    -- set to ``True`` to skip logging

Usage from a route handler::

    @router.post("/cases/{case_id}/status")
    async def change_status(case_id: UUID, ..., request: Request):
        request.state.audit_action = "case.status_changed"
        request.state.audit_details = {
            "old_status": "received",
            "new_status": "in_review",
        }
        ...
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────

# HTTP methods that represent state changes and should be audited.
_STATE_CHANGING_METHODS: frozenset[str] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE"}
)

# Paths exempt from audit logging (health checks, docs, static).
_AUDIT_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
)

# ── Path-to-action mapping ────────────────────────────────────
# Maps (method, path_prefix) to AuditAction enum values.
# Order matters: first match wins.  More specific prefixes first.

_PATH_ACTION_MAP: list[tuple[str, str, str]] = [
    # Case lifecycle
    ("POST", "/api/v1/reports", "case.created"),
    ("POST", "/api/v1/complaints", "case.created"),
    ("PUT", "/api/v1/admin/cases/", "case.status_changed"),
    ("PATCH", "/api/v1/admin/cases/", "case.status_changed"),
    ("DELETE", "/api/v1/admin/cases/", "case.deleted"),
    # Messages
    ("POST", "/api/v1/admin/cases/", "message.sent"),  # /cases/{id}/messages
    ("POST", "/api/v1/reports/", "message.sent"),  # reporter sending message
    # Attachments
    ("POST", "/api/v1/attachments", "attachment.uploaded"),
    # Identity disclosure (4-eyes)
    ("POST", "/api/v1/admin/cases/", "identity.disclosure_requested"),
    # User management
    ("POST", "/api/v1/admin/users", "user.created"),
    ("PUT", "/api/v1/admin/users/", "user.updated"),
    ("PATCH", "/api/v1/admin/users/", "user.updated"),
    ("DELETE", "/api/v1/admin/users/", "user.deactivated"),
    # Tenant management
    ("POST", "/api/v1/admin/tenants", "tenant.created"),
    ("PUT", "/api/v1/admin/tenants/", "tenant.updated"),
    ("PATCH", "/api/v1/admin/tenants/", "tenant.updated"),
    ("DELETE", "/api/v1/admin/tenants/", "tenant.deactivated"),
    # Category management
    ("POST", "/api/v1/admin/categories", "category.created"),
    ("PUT", "/api/v1/admin/categories/", "category.updated"),
    ("PATCH", "/api/v1/admin/categories/", "category.updated"),
    ("DELETE", "/api/v1/admin/categories/", "category.deleted"),
    # Reporter access
    ("POST", "/api/v1/auth/magic-link", "magic_link.requested"),
    ("POST", "/api/v1/auth/mailbox", "mailbox.login"),
    # Auth
    ("POST", "/api/v1/auth/login", "user.login"),
    ("POST", "/api/v1/auth/logout", "user.logout"),
    # Data retention
    ("POST", "/api/v1/admin/data-retention", "data_retention.executed"),
]


def _is_exempt(path: str) -> bool:
    """Return ``True`` if *path* should not be audited."""
    return any(path.startswith(prefix) for prefix in _AUDIT_EXEMPT_PREFIXES)


def _detect_action(method: str, path: str) -> str | None:
    """Derive an audit action string from the HTTP method and path.

    Returns ``None`` if no mapping matches (the request will still be
    logged with a generic action).
    """
    for map_method, map_prefix, action in _PATH_ACTION_MAP:
        if method == map_method and path.startswith(map_prefix):
            return action
    return None


def _extract_resource(path: str) -> tuple[str, str]:
    """Extract a ``(resource_type, resource_id)`` pair from the URL path.

    Heuristic: the path segment immediately after ``/api/v1/`` (or
    ``/api/v1/admin/``) is the resource type, and the next UUID-like
    segment is the resource ID.

    Examples::

        /api/v1/reports              -> ("reports",  "")
        /api/v1/admin/cases/abc-123  -> ("cases",    "abc-123")
        /api/v1/admin/users/xyz      -> ("users",    "xyz")
    """
    # Strip leading /api/v1/ or /api/v1/admin/
    stripped = path
    if stripped.startswith("/api/v1/admin/"):
        stripped = stripped[len("/api/v1/admin/"):]
    elif stripped.startswith("/api/v1/"):
        stripped = stripped[len("/api/v1/"):]

    parts = [p for p in stripped.split("/") if p]

    resource_type = parts[0] if parts else "unknown"
    resource_id = parts[1] if len(parts) >= 2 else ""

    return resource_type, resource_id


def _get_actor_info(request: Request) -> tuple[uuid.UUID | None, str]:
    """Extract actor ID and type from the request state.

    Returns ``(actor_id, actor_type)`` where:

    - ``actor_id`` is the authenticated user's UUID or ``None``
    - ``actor_type`` is ``"user"``, ``"reporter"``, or ``"system"``

    The authentication middleware / dependencies should set:

    - ``request.state.user_id``   (UUID) for authenticated admin users
    - ``request.state.reporter``  (bool) for reporter sessions
    """
    # Authenticated admin user
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return user_id, "user"

    # Reporter (anonymous or identified)
    is_reporter = getattr(request.state, "reporter", False)
    if is_reporter:
        return None, "reporter"

    return None, "system"


def _get_ip_address(request: Request, actor_type: str) -> str | None:
    """Get the client IP address, respecting anonymity rules.

    Returns ``None`` for reporter actions to protect anonymity
    (the AnonymityMiddleware already replaces the real IP, but we
    enforce it here as a defence-in-depth measure).
    """
    if actor_type == "reporter":
        return None

    # Prefer the real IP forwarded by Caddy
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded

    client = request.client
    if client:
        return client.host

    return None


# ── Middleware ─────────────────────────────────────────────────


class AuditLoggerMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that writes an audit log entry for every
    state-changing request (POST, PUT, PATCH, DELETE).

    The entry is written **after** the response is generated so that
    route handlers have a chance to enrich the audit data via
    ``request.state`` attributes.

    Non-state-changing requests (GET, HEAD, OPTIONS) and exempt paths
    (health, docs) are passed through without logging.

    If the audit write fails (e.g. database unavailable) the error is
    logged but the original response is still returned -- audit failures
    must never break the application.
    """

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        """Process the request and write an audit log entry if applicable."""
        path = request.url.path
        method = request.method

        # ── Skip non-state-changing requests ─────────────────
        if method not in _STATE_CHANGING_METHODS:
            return await call_next(request)

        # ── Skip exempt paths ────────────────────────────────
        if _is_exempt(path):
            return await call_next(request)

        # ── Execute the downstream handler ───────────────────
        response: Response = await call_next(request)

        # ── Check if the handler requested to skip auditing ──
        if getattr(request.state, "audit_skip", False):
            return response

        # ── Write audit entry (fire-and-forget style) ────────
        try:
            await _write_audit_entry(request, response, method, path)
        except Exception:
            # Never let audit failures break the application.
            logger.exception(
                "audit_write_failed",
                method=method,
                path=path,
            )

        return response


async def _write_audit_entry(
    request: Request,
    response: Response,
    method: str,
    path: str,
) -> None:
    """Construct and persist an audit log entry.

    Reads optional overrides from ``request.state`` (set by route
    handlers) and falls back to auto-detection from the URL.
    """
    from app.core.database import get_session_factory
    from app.models.audit_log import AuditAction, AuditLog

    # ── Resolve tenant ───────────────────────────────────────
    tenant_id: uuid.UUID | None = getattr(
        request.state, "tenant_id", None
    )
    if tenant_id is None:
        # Cannot write an audit entry without a tenant context.
        logger.debug(
            "audit_skipped_no_tenant",
            method=method,
            path=path,
        )
        return

    # ── Determine action ─────────────────────────────────────
    action_str: str | None = getattr(
        request.state, "audit_action", None
    )
    if action_str is None:
        action_str = _detect_action(method, path)
    if action_str is None:
        # Generic fallback based on HTTP method
        action_str = f"http.{method.lower()}"

    # Resolve to AuditAction enum; fall back gracefully if the
    # action string does not match any enum member.
    try:
        action = AuditAction(action_str)
    except ValueError:
        # Action string not in enum -- log as system event and
        # store the raw string in details.
        action = AuditAction.SYSTEM_ERROR
        extra_details: dict[str, Any] = {
            "unmapped_action": action_str,
        }
    else:
        extra_details = {}

    # ── Actor info ───────────────────────────────────────────
    actor_id, actor_type = _get_actor_info(request)

    # ── Resource identification ──────────────────────────────
    resource_type = getattr(request.state, "audit_resource_type", None)
    resource_id = getattr(request.state, "audit_resource_id", None)

    if resource_type is None or resource_id is None:
        auto_type, auto_id = _extract_resource(path)
        resource_type = resource_type or auto_type
        resource_id = resource_id or auto_id or ""

    # ── Details ──────────────────────────────────────────────
    handler_details: dict[str, Any] | None = getattr(
        request.state, "audit_details", None
    )
    details: dict[str, Any] = {}
    if handler_details:
        details.update(handler_details)
    if extra_details:
        details.update(extra_details)

    # Include HTTP status code for context
    details["http_status"] = response.status_code
    details["http_method"] = method
    details["path"] = path

    # ── Context ──────────────────────────────────────────────
    ip_address = _get_ip_address(request, actor_type)
    user_agent = request.headers.get("user-agent")

    # ── Persist the entry ────────────────────────────────────
    try:
        factory = get_session_factory()
    except RuntimeError:
        logger.warning("audit_write_skipped_db_not_ready")
        return

    async with factory() as session:
        entry = AuditLog(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details if details else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(entry)
        await session.commit()

        logger.info(
            "audit_entry_written",
            action=action.value,
            actor_type=actor_type,
            resource=f"{resource_type}/{resource_id}",
            tenant_id=str(tenant_id),
        )


# ── Helper for manual audit logging from services ────────────


async def write_audit_log(
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_type: str = "system",
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Write an audit log entry directly from service code.

    This is the programmatic API for audit logging, used by services
    and background tasks that are not triggered by an HTTP request
    (e.g. scheduled data retention, system events).

    Parameters
    ----------
    tenant_id:
        UUID of the tenant.
    action:
        The audit action string (should match an ``AuditAction`` enum
        value, e.g. ``"data_retention.executed"``).
    actor_id:
        UUID of the user performing the action, or ``None`` for
        anonymous/system.
    actor_type:
        ``"user"``, ``"reporter"``, or ``"system"``.
    resource_type:
        Type of affected resource (e.g. ``"report"``, ``"user"``).
    resource_id:
        ID of the affected resource.
    details:
        Optional dict with action-specific data (old/new values, etc.).
    ip_address:
        Client IP address (``None`` for reporter/system actions).
    user_agent:
        HTTP User-Agent header value.

    Raises
    ------
    RuntimeError
        If the database engine is not initialised.
    """
    from app.core.database import get_session_factory
    from app.models.audit_log import AuditAction, AuditLog

    try:
        action_enum = AuditAction(action)
    except ValueError:
        action_enum = AuditAction.SYSTEM_ERROR
        details = {**(details or {}), "unmapped_action": action}

    factory = get_session_factory()
    async with factory() as session:
        entry = AuditLog(
            tenant_id=tenant_id,
            action=action_enum,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(entry)
        await session.commit()

    logger.info(
        "audit_entry_written",
        action=action_enum.value,
        actor_type=actor_type,
        resource=f"{resource_type}/{resource_id}",
        tenant_id=str(tenant_id),
    )
