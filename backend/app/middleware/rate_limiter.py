"""Hinweisgebersystem -- Redis-based Rate Limiter Middleware.

Enforces per-endpoint request rate limits using a sliding window
algorithm backed by Redis sorted sets.  When a client exceeds the
configured limit the middleware returns an HTTP ``429 Too Many Requests``
response with ``Retry-After`` and ``X-RateLimit-*`` headers.

Architecture:

- **Sliding window** -- Uses Redis sorted sets (ZRANGEBYSCORE + ZCARD)
  to count requests within a rolling time window.  This avoids the
  boundary problems of fixed windows and the memory overhead of token
  buckets.
- **Per-endpoint configuration** -- Different endpoints can have
  different limits.  The ``_RATE_LIMIT_RULES`` table maps path prefixes
  and HTTP methods to ``(max_requests, window_seconds)`` tuples.
- **Key strategy** -- Rate limit keys combine the client IP (or email
  for magic-link endpoints) with the path prefix, scoped per tenant
  where applicable.
- **Graceful degradation** -- If Redis is unavailable the middleware
  allows the request through (fail-open) and logs a warning.

Configured limits (from spec):

- **Report submission**: 5 requests per IP per hour
  (``POST /api/v1/reports``, ``POST /api/v1/complaints``)
- **Magic link requests**: 3 requests per email per hour
  (``POST /api/v1/auth/magic-link``)
- **Mailbox login**: 10 requests per IP per 15 minutes
  (``POST /api/v1/auth/mailbox``)
- **Admin API (default)**: 60 requests per user per minute
  (``POST|PUT|PATCH|DELETE /api/v1/admin/*``)

Usage::

    from app.middleware.rate_limiter import RateLimiterMiddleware

    # In main.py _configure_middleware():
    application.add_middleware(RateLimiterMiddleware)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)


# ── Rate limit rule definition ───────────────────────────────


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """Defines a rate limit for a specific endpoint pattern.

    Attributes
    ----------
    method : str
        HTTP method to match (e.g. ``"POST"``).  Use ``"*"`` for any.
    path_prefix : str
        URL path prefix to match (e.g. ``"/api/v1/reports"``).
    max_requests : int
        Maximum number of requests allowed within the window.
    window_seconds : int
        Sliding window duration in seconds.
    key_type : str
        How to derive the rate limit key:
        - ``"ip"`` -- client IP address (default for public endpoints)
        - ``"email"`` -- email from request body (magic link endpoint)
        - ``"user"`` -- authenticated user ID (admin endpoints)
    description : str
        Human-readable description for logging and headers.
    """

    method: str
    path_prefix: str
    max_requests: int
    window_seconds: int
    key_type: str = "ip"
    description: str = ""


# ── Configured rate limit rules ──────────────────────────────
# Order matters: first match wins.  More specific prefixes first.

_RATE_LIMIT_RULES: list[RateLimitRule] = [
    # Magic link: 3 per email per hour
    RateLimitRule(
        method="POST",
        path_prefix="/api/v1/auth/magic-link",
        max_requests=3,
        window_seconds=3600,
        key_type="email",
        description="magic_link_request",
    ),
    # Mailbox login: 10 per IP per 15 minutes
    RateLimitRule(
        method="POST",
        path_prefix="/api/v1/reports/verify",
        max_requests=10,
        window_seconds=900,
        key_type="ip",
        description="mailbox_login",
    ),
    # Report submission (HinSchG): 5 per IP per hour
    RateLimitRule(
        method="POST",
        path_prefix="/api/v1/reports",
        max_requests=5,
        window_seconds=3600,
        key_type="ip",
        description="report_submit",
    ),
    # LkSG complaints: 5 per IP per hour
    RateLimitRule(
        method="POST",
        path_prefix="/api/v1/public/complaints",
        max_requests=5,
        window_seconds=3600,
        key_type="ip",
        description="complaint_submit",
    ),
    # Admin API mutations: 60 per user per minute
    RateLimitRule(
        method="*",
        path_prefix="/api/v1/admin/",
        max_requests=60,
        window_seconds=60,
        key_type="user",
        description="admin_api",
    ),
]

# Paths exempt from rate limiting entirely.
_RATE_EXEMPT_PREFIXES = (
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
)

# HTTP methods considered for rate limiting (state-changing + reads).
_RATE_LIMITED_METHODS: frozenset[str] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE"}
)


def _is_exempt(path: str) -> bool:
    """Return ``True`` if *path* should not be rate-limited."""
    return any(path.startswith(prefix) for prefix in _RATE_EXEMPT_PREFIXES)


# ── Rule matching ────────────────────────────────────────────


def _find_rule(method: str, path: str) -> RateLimitRule | None:
    """Find the first matching rate limit rule for the request.

    Returns ``None`` if no rule matches (request is not rate-limited).
    """
    for rule in _RATE_LIMIT_RULES:
        if rule.method != "*" and rule.method != method:
            continue
        if path.startswith(rule.path_prefix):
            return rule
    return None


# ── Key extraction ───────────────────────────────────────────


def _get_client_ip(request: Request) -> str:
    """Extract the client IP address from the request.

    Prefers ``X-Real-IP`` (set by Caddy) over the raw ASGI client
    address for accuracy behind a reverse proxy.
    """
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded.strip()

    client = request.client
    if client:
        return client.host

    return "unknown"


async def _get_rate_limit_key(
    request: Request,
    rule: RateLimitRule,
) -> str:
    """Build the Redis key for rate limiting.

    The key format is::

        ratelimit:{description}:{identifier}

    Where ``identifier`` depends on the ``key_type``:

    - ``"ip"``    -- client IP address
    - ``"email"`` -- email from the request body (cached in state)
    - ``"user"``  -- authenticated user UUID from request state
    """
    prefix = f"ratelimit:{rule.description}"

    if rule.key_type == "email":
        # Try to extract email from the cached request body.
        # The body is consumed here and must be cached for downstream
        # handlers.  We store it in request.state to avoid double-read.
        email = await _extract_email_from_body(request)
        if email:
            return f"{prefix}:{email.lower()}"
        # Fallback to IP if email extraction fails
        return f"{prefix}:{_get_client_ip(request)}"

    if rule.key_type == "user":
        user_id = getattr(request.state, "user_id", None)
        if user_id is not None:
            return f"{prefix}:{user_id}"
        # Fallback to IP for unauthenticated requests
        return f"{prefix}:{_get_client_ip(request)}"

    # Default: IP-based
    return f"{prefix}:{_get_client_ip(request)}"


async def _extract_email_from_body(request: Request) -> str | None:
    """Extract the ``email`` field from a JSON request body.

    Caches the raw body bytes in ``request.state._cached_body`` so that
    downstream handlers can still read the body.  Returns ``None`` if
    the body cannot be parsed or does not contain an ``email`` field.
    """
    import json

    try:
        # Check if we already cached the body
        cached = getattr(request.state, "_cached_body", None)
        if cached is not None:
            body_bytes = cached
        else:
            body_bytes = await request.body()
            request.state._cached_body = body_bytes

        if not body_bytes:
            return None

        data: dict[str, Any] = json.loads(body_bytes)
        email = data.get("email")
        if isinstance(email, str) and email:
            return email
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    except Exception:
        logger.debug("rate_limit_email_extraction_failed")

    return None


# ── Sliding window implementation ────────────────────────────


async def _check_rate_limit(
    key: str,
    rule: RateLimitRule,
) -> tuple[bool, int, int]:
    """Check whether the request is within the rate limit.

    Uses Redis sorted sets with the sliding window algorithm:

    1. Remove all entries older than ``now - window_seconds``.
    2. Count remaining entries (current request count).
    3. If under the limit, add the current timestamp.
    4. Set the key TTL to ``window_seconds`` for automatic cleanup.

    Parameters
    ----------
    key:
        The Redis key for this client + endpoint combination.
    rule:
        The rate limit rule with max_requests and window_seconds.

    Returns
    -------
    tuple[bool, int, int]
        ``(allowed, remaining, reset_after_seconds)`` where:
        - ``allowed`` is ``True`` if the request should proceed
        - ``remaining`` is the number of requests left in the window
        - ``reset_after_seconds`` is seconds until the window resets
    """
    from redis import asyncio as aioredis

    from app.core.config import settings

    now = time.time()
    window_start = now - rule.window_seconds

    try:
        redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception:
        logger.warning("rate_limit_redis_connect_failed", key=key)
        return True, rule.max_requests, rule.window_seconds

    # Atomic check-and-increment via Lua script to prevent race conditions.
    _RATE_LIMIT_LUA = """
    local key = KEYS[1]
    local window_start = tonumber(ARGV[1])
    local now = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local window_seconds = tonumber(ARGV[4])

    redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
    local current_count = redis.call('ZCARD', key)

    if current_count >= max_requests then
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local reset_after = window_seconds
        if #oldest >= 2 then
            reset_after = math.ceil(tonumber(oldest[2]) + window_seconds - now) + 1
        end
        return {0, 0, math.max(reset_after, 1)}
    end

    redis.call('ZADD', key, now, tostring(now))
    redis.call('EXPIRE', key, window_seconds)
    local remaining = max_requests - current_count - 1
    return {1, math.max(remaining, 0), window_seconds}
    """

    try:
        result = await redis.eval(
            _RATE_LIMIT_LUA,
            1,
            key,
            str(window_start),
            str(now),
            str(rule.max_requests),
            str(rule.window_seconds),
        )

        allowed = result[0] == 1
        remaining = int(result[1])
        reset_or_window = int(result[2])
        return allowed, remaining, reset_or_window

    except Exception:
        # Fail open: allow the request if Redis is unavailable.
        logger.warning(
            "rate_limit_check_failed",
            key=key,
            exc_info=True,
        )
        return True, rule.max_requests, rule.window_seconds
    finally:
        await redis.aclose()


# ── Middleware ─────────────────────────────────────────────────


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces Redis-based sliding-window rate limits.

    Configured per-endpoint via ``_RATE_LIMIT_RULES``.  Returns a
    ``429 Too Many Requests`` JSON response with standard rate limit
    headers when a client exceeds the allowed request count.

    Response headers (always set when a rule matches):

    - ``X-RateLimit-Limit``: maximum requests in the window
    - ``X-RateLimit-Remaining``: requests left in the current window
    - ``X-RateLimit-Reset``: seconds until the window resets

    On 429 responses the ``Retry-After`` header is also set.

    If Redis is unavailable the middleware fails open (allows the
    request) and logs a warning.  Rate limiting should never block
    legitimate traffic due to infrastructure issues.
    """

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        """Check rate limits and either forward or reject the request."""
        path = request.url.path
        method = request.method

        # ── Skip non-rate-limited methods ───────────────────────
        if method not in _RATE_LIMITED_METHODS:
            return await call_next(request)

        # ── Skip exempt paths ───────────────────────────────────
        if _is_exempt(path):
            return await call_next(request)

        # ── Find matching rule ──────────────────────────────────
        rule = _find_rule(method, path)
        if rule is None:
            return await call_next(request)

        # ── Build rate limit key ────────────────────────────────
        key = await _get_rate_limit_key(request, rule)

        # ── Check the limit ─────────────────────────────────────
        allowed, remaining, reset_after = await _check_rate_limit(key, rule)

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                rule=rule.description,
                limit=rule.max_requests,
                window=rule.window_seconds,
                client_ip=_get_client_ip(request),
                path=path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after": reset_after,
                },
                headers={
                    "Retry-After": str(reset_after),
                    "X-RateLimit-Limit": str(rule.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_after),
                },
            )

        # ── Forward the request ─────────────────────────────────
        response: Response = await call_next(request)

        # ── Attach rate limit headers to the response ───────────
        response.headers["X-RateLimit-Limit"] = str(rule.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_after)

        return response


# ── Utility functions ────────────────────────────────────────


async def reset_rate_limit(key: str) -> None:
    """Remove all rate limit entries for a specific key.

    Useful for administrative actions (e.g. unlocking a user after
    a false-positive lockout).

    Parameters
    ----------
    key:
        The full Redis key (e.g. ``"ratelimit:magic_link_request:user@example.com"``).
    """
    from redis import asyncio as aioredis

    from app.core.config import settings

    try:
        redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            await redis.delete(key)
            logger.info("rate_limit_reset", key=key)
        finally:
            await redis.aclose()
    except Exception:
        logger.warning("rate_limit_reset_failed", key=key, exc_info=True)


async def get_rate_limit_status(key: str, rule_description: str) -> dict[str, Any]:
    """Query the current rate limit status for a key.

    Returns a dict with ``count``, ``limit``, ``remaining``, and
    ``window_seconds`` fields.  Useful for admin dashboards and
    monitoring.

    Parameters
    ----------
    key:
        The full Redis key.
    rule_description:
        The rule description to look up the limit configuration.

    Returns
    -------
    dict
        Rate limit status information.
    """
    from redis import asyncio as aioredis

    from app.core.config import settings

    # Find the matching rule by description
    rule = next(
        (r for r in _RATE_LIMIT_RULES if r.description == rule_description),
        None,
    )
    if rule is None:
        return {"error": "Rule not found", "description": rule_description}

    now = time.time()
    window_start = now - rule.window_seconds

    try:
        redis: aioredis.Redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            # Clean expired and count
            await redis.zremrangebyscore(key, 0, window_start)
            count = await redis.zcard(key)

            return {
                "key": key,
                "description": rule.description,
                "count": count,
                "limit": rule.max_requests,
                "remaining": max(rule.max_requests - count, 0),
                "window_seconds": rule.window_seconds,
            }
        finally:
            await redis.aclose()
    except Exception:
        logger.warning("rate_limit_status_failed", key=key, exc_info=True)
        return {
            "key": key,
            "description": rule.description,
            "error": "Redis unavailable",
        }
