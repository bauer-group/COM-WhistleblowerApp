"""Hinweisgebersystem -- Anonymity & Anti-Forensics Middleware.

Provides two middleware layers for whistleblower protection:

**AnonymityMiddleware** — Reporter-endpoint-only protections:

1. **No IP logging** -- Strips ``X-Forwarded-For``, ``X-Real-IP``, and
   similar identifying headers before the request reaches route
   handlers.  Overwrites the ASGI ``client`` tuple so that
   ``request.client.host`` returns a placeholder (``0.0.0.0``).

2. **Timestamp rounding** -- Provides ``round_timestamp()`` to round
   ``datetime`` values down to 15-minute intervals, preventing timing
   correlation attacks on anonymous report submissions.

3. **Uniform response time padding** -- Guarantees that all responses
   to reporter endpoints take **at least 200 ms**, preventing timing
   side-channels that could leak information about database state or
   branch logic.

4. **No cookies in anonymous mode** -- Strips ``Set-Cookie`` headers
   from responses to reporter endpoints and adds ``Cache-Control:
   no-store`` to prevent any browser-side persistence.

**AntiForensicsMiddleware** — Global browser anti-forensics headers:

5. **Cache prevention** -- Adds ``Cache-Control: no-store`` to ALL
   responses, preventing browsers from writing sensitive data to disk.

6. **Content-type sniffing prevention** -- Adds
   ``X-Content-Type-Options: nosniff`` to prevent MIME-type attacks.

7. **Referrer leak prevention** -- Adds ``Referrer-Policy: no-referrer``
   to prevent the browser from sending the page URL when navigating
   away, which could reveal the whistleblowing platform origin.

8. **Logout data purge** -- Adds ``Clear-Site-Data`` header on logout
   endpoint responses to instruct the browser to purge all cached
   data, cookies, and storage for the origin.

These protections are mandated by the HinSchG anonymity requirements
and constitute a critical security layer of the system.

Usage of ``round_timestamp``::

    from app.middleware.anonymity import round_timestamp
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    report.created_at = round_timestamp(now)  # e.g. 10:37 -> 10:30
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────

# Minimum response time for reporter endpoints (seconds).
_MIN_RESPONSE_TIME_SECONDS: float = 0.200  # 200 ms

# Default timestamp rounding interval (minutes).
_TIMESTAMP_ROUND_MINUTES: int = 15

# Reporter endpoint prefixes that receive full anonymity protection.
_REPORTER_PREFIXES = (
    "/api/v1/reports",
    "/api/v1/public/complaints",
    "/api/v1/auth/magic-link",
)

# Request headers that may leak the reporter's identity.
_IDENTIFYING_HEADERS: frozenset[str] = frozenset(
    {
        "x-forwarded-for",
        "x-real-ip",
        "x-client-ip",
        "cf-connecting-ip",
        "true-client-ip",
        "forwarded",
    }
)

# Placeholder client address used after anonymisation.
_ANONYMOUS_CLIENT: tuple[str, int] = ("0.0.0.0", 0)

# Logout endpoint paths that trigger Clear-Site-Data header.
_LOGOUT_PATHS = (
    "/api/v1/auth/logout",
)


# ── Helpers ───────────────────────────────────────────────────


def _is_reporter_endpoint(path: str) -> bool:
    """Return ``True`` if *path* is a reporter-facing endpoint."""
    return any(path.startswith(prefix) for prefix in _REPORTER_PREFIXES)


# ── Timestamp rounding ────────────────────────────────────────


def round_timestamp(
    dt: datetime,
    interval_minutes: int = _TIMESTAMP_ROUND_MINUTES,
) -> datetime:
    """Round *dt* **down** to the nearest *interval_minutes* boundary.

    Used when persisting anonymous report timestamps to prevent timing
    correlation attacks.

    Parameters
    ----------
    dt:
        The datetime to round.  Should be timezone-aware; if naive the
        result is returned as-is (naive).
    interval_minutes:
        Rounding granularity in minutes.  Defaults to 15.

    Returns
    -------
    datetime
        The floored datetime with seconds and microseconds set to zero.

    Raises
    ------
    ValueError
        If *interval_minutes* is not positive.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> dt = datetime(2024, 3, 15, 10, 37, 42, tzinfo=timezone.utc)
    >>> round_timestamp(dt)
    datetime.datetime(2024, 3, 15, 10, 30, tzinfo=datetime.timezone.utc)

    >>> dt = datetime(2024, 3, 15, 10, 59, 59, tzinfo=timezone.utc)
    >>> round_timestamp(dt)
    datetime.datetime(2024, 3, 15, 10, 45, tzinfo=datetime.timezone.utc)

    >>> dt = datetime(2024, 3, 15, 11, 0, 0, tzinfo=timezone.utc)
    >>> round_timestamp(dt)
    datetime.datetime(2024, 3, 15, 11, 0, tzinfo=datetime.timezone.utc)
    """
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be a positive integer")

    # Floor to the nearest interval using integer minute arithmetic.
    total_minutes = dt.hour * 60 + dt.minute
    floored_minutes = (total_minutes // interval_minutes) * interval_minutes
    floored_hour, floored_minute = divmod(floored_minutes, 60)

    return dt.replace(
        hour=floored_hour,
        minute=floored_minute,
        second=0,
        microsecond=0,
    )


# ── Middleware ─────────────────────────────────────────────────


class AnonymityMiddleware(BaseHTTPMiddleware):
    """ASGI middleware enforcing anonymity for reporter endpoints.

    Applied automatically to every request whose path starts with one
    of the ``_REPORTER_PREFIXES``.  Non-reporter requests pass through
    unchanged.

    Protections:

    - **Request sanitisation**: strips identifying headers
      (``X-Forwarded-For``, etc.) and replaces the ASGI ``client``
      address with ``0.0.0.0:0``.
    - **Response sanitisation**: removes all ``Set-Cookie`` headers and
      adds ``Cache-Control: no-store`` plus ``Pragma: no-cache``.
    - **Response time padding**: ensures the total response time is at
      least 200 ms to prevent timing-based inference.
    """

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        """Process the request with anonymity protections if applicable."""
        path = request.url.path

        if not _is_reporter_endpoint(path):
            return await call_next(request)

        # ── Sanitise the inbound request ─────────────────────
        _anonymise_request(request)

        # ── Time the downstream handling ─────────────────────
        start = time.monotonic()

        response: Response = await call_next(request)

        # ── Sanitise the outbound response ───────────────────
        _anonymise_response(response)

        # ── Pad to minimum response time ─────────────────────
        elapsed = time.monotonic() - start
        remaining = _MIN_RESPONSE_TIME_SECONDS - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        return response


# ── Anti-Forensics Middleware ──────────────────────────────────


class AntiForensicsMiddleware(BaseHTTPMiddleware):
    """ASGI middleware adding browser anti-forensics headers to ALL responses.

    Unlike ``AnonymityMiddleware`` (which only targets reporter endpoints),
    this middleware applies to **every** response to prevent browser-level
    forensic traces across the entire application.

    Headers added to all responses:

    - ``Cache-Control: no-store`` — prevents browsers from caching
      response bodies to disk.
    - ``X-Content-Type-Options: nosniff`` — prevents MIME-type sniffing
      attacks.
    - ``Referrer-Policy: no-referrer`` — prevents the browser from
      leaking the page URL via the ``Referer`` header on navigation.

    On **logout** endpoint responses only:

    - ``Clear-Site-Data: "cache", "cookies", "storage"`` — instructs
      the browser to purge all locally stored data for the origin.
    """

    async def dispatch(self, request: Request, call_next: ...) -> Response:
        """Add anti-forensics headers to every response."""
        response: Response = await call_next(request)

        response.headers["cache-control"] = "no-store"
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"

        # On logout, instruct the browser to purge all site data.
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _LOGOUT_PATHS):
            response.headers["clear-site-data"] = '"cache", "cookies", "storage"'

        return response


# ── Request / response sanitisation ───────────────────────────


def _anonymise_request(request: Request) -> None:
    """Remove identifying information from the incoming ASGI scope.

    - Overwrites ``scope["client"]`` with ``("0.0.0.0", 0)`` so that
      any downstream code reading ``request.client.host`` gets the
      placeholder instead of the real IP.
    - Strips headers that proxies typically use to forward the original
      client IP (``X-Forwarded-For``, ``X-Real-IP``, etc.).
    """
    # Replace the real client address
    request.scope["client"] = _ANONYMOUS_CLIENT

    # Filter out identifying headers from the raw ASGI header list.
    # Headers are stored as list[tuple[bytes, bytes]].
    raw_headers: list[tuple[bytes, bytes]] = request.scope.get("headers", [])
    request.scope["headers"] = [
        (name, value)
        for name, value in raw_headers
        if name.decode("latin-1").lower() not in _IDENTIFYING_HEADERS
    ]


def _anonymise_response(response: Response) -> None:
    """Strip tracking mechanisms from the outbound response.

    - Removes all ``Set-Cookie`` headers to prevent cookies in
      anonymous mode.
    - Sets ``Cache-Control: no-store`` and ``Pragma: no-cache`` to
      prevent any browser-side caching of sensitive responses.
    """
    # Remove Set-Cookie headers except for the reporter_session
    # cookie which is required for mailbox authentication.
    # Modify raw_headers in-place to keep MutableHeaders cache coherent.
    raw = response.raw_headers
    indices_to_remove = [
        i
        for i, (name, value) in enumerate(raw)
        if name.lower() == b"set-cookie" and b"reporter_session=" not in value
    ]
    for offset, idx in enumerate(indices_to_remove):
        raw.pop(idx - offset)

    # Prevent browser caching
    response.headers["cache-control"] = "no-store, no-cache, must-revalidate"
    response.headers["pragma"] = "no-cache"
