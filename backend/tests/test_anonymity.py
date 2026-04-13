"""Hinweisgebersystem -- Anonymity Protection Tests.

Tests:
- Timestamp rounding to 15-minute intervals (various edge cases).
- Response time padding ≥ 200 ms on reporter endpoints.
- IP address removal from request context (headers + ASGI client).
- Cookie stripping and cache-control headers on anonymous responses.
- Non-reporter endpoints pass through unmodified.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from app.middleware.anonymity import (
    AnonymityMiddleware,
    _ANONYMOUS_CLIENT,
    _IDENTIFYING_HEADERS,
    _MIN_RESPONSE_TIME_SECONDS,
    _REPORTER_PREFIXES,
    _TIMESTAMP_ROUND_MINUTES,
    _anonymise_request,
    _anonymise_response,
    _is_reporter_endpoint,
    round_timestamp,
)


# ── Timestamp Rounding ───────────────────────────────────────


class TestRoundTimestamp:
    """Tests for ``round_timestamp`` — rounds down to 15-min intervals."""

    def test_exact_boundary_unchanged(self):
        """A timestamp on an exact 15-minute boundary must not change."""
        dt = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == dt

    def test_exact_15_unchanged(self):
        """10:15:00 is on a boundary and must stay unchanged."""
        dt = datetime(2024, 3, 15, 10, 15, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == dt

    def test_exact_30_unchanged(self):
        """10:30:00 is on a boundary and must stay unchanged."""
        dt = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == dt

    def test_exact_45_unchanged(self):
        """10:45:00 is on a boundary and must stay unchanged."""
        dt = datetime(2024, 3, 15, 10, 45, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == dt

    def test_rounds_down_to_30(self):
        """10:37:42 must round down to 10:30:00."""
        dt = datetime(2024, 3, 15, 10, 37, 42, tzinfo=timezone.utc)
        expected = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == expected

    def test_rounds_down_to_45(self):
        """10:59:59 must round down to 10:45:00."""
        dt = datetime(2024, 3, 15, 10, 59, 59, tzinfo=timezone.utc)
        expected = datetime(2024, 3, 15, 10, 45, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == expected

    def test_midnight_boundary(self):
        """00:07:00 must round down to 00:00:00."""
        dt = datetime(2024, 1, 1, 0, 7, 0, tzinfo=timezone.utc)
        expected = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == expected

    def test_end_of_day(self):
        """23:59:59 must round down to 23:45:00."""
        dt = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        expected = datetime(2024, 12, 31, 23, 45, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt) == expected

    def test_seconds_zeroed(self):
        """Seconds must be set to zero after rounding."""
        dt = datetime(2024, 6, 1, 14, 30, 45, tzinfo=timezone.utc)
        result = round_timestamp(dt)
        assert result.second == 0

    def test_microseconds_zeroed(self):
        """Microseconds must be set to zero after rounding."""
        dt = datetime(2024, 6, 1, 14, 30, 0, 123456, tzinfo=timezone.utc)
        result = round_timestamp(dt)
        assert result.microsecond == 0

    def test_preserves_timezone(self):
        """Timezone must be preserved after rounding."""
        dt = datetime(2024, 6, 1, 10, 37, 0, tzinfo=timezone.utc)
        result = round_timestamp(dt)
        assert result.tzinfo == timezone.utc

    def test_preserves_date(self):
        """Date components must not be altered by rounding."""
        dt = datetime(2024, 6, 15, 10, 37, 42, tzinfo=timezone.utc)
        result = round_timestamp(dt)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_custom_interval_10_minutes(self):
        """Custom 10-minute interval: 10:37 -> 10:30."""
        dt = datetime(2024, 3, 15, 10, 37, 0, tzinfo=timezone.utc)
        expected = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt, interval_minutes=10) == expected

    def test_custom_interval_30_minutes(self):
        """Custom 30-minute interval: 10:37 -> 10:30."""
        dt = datetime(2024, 3, 15, 10, 37, 0, tzinfo=timezone.utc)
        expected = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt, interval_minutes=30) == expected

    def test_custom_interval_60_minutes(self):
        """Custom 60-minute interval: 10:37 -> 10:00."""
        dt = datetime(2024, 3, 15, 10, 37, 0, tzinfo=timezone.utc)
        expected = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert round_timestamp(dt, interval_minutes=60) == expected

    def test_invalid_interval_zero(self):
        """``interval_minutes=0`` must raise ``ValueError``."""
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="positive integer"):
            round_timestamp(dt, interval_minutes=0)

    def test_invalid_interval_negative(self):
        """Negative ``interval_minutes`` must raise ``ValueError``."""
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="positive integer"):
            round_timestamp(dt, interval_minutes=-15)

    def test_naive_datetime(self):
        """Naive datetime must be handled without error."""
        dt = datetime(2024, 3, 15, 10, 37, 42)
        result = round_timestamp(dt)
        assert result == datetime(2024, 3, 15, 10, 30, 0)
        assert result.tzinfo is None

    def test_default_interval_is_15(self):
        """Default interval must be 15 minutes."""
        assert _TIMESTAMP_ROUND_MINUTES == 15


# ── Reporter Endpoint Detection ──────────────────────────────


class TestIsReporterEndpoint:
    """Tests for ``_is_reporter_endpoint``."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/reports",
            "/api/v1/reports/",
            "/api/v1/reports/submit",
            "/api/v1/reports/abc-123/messages",
            "/api/v1/public/complaints",
            "/api/v1/public/complaints/new",
            "/api/v1/auth/magic-link",
            "/api/v1/auth/magic-link/verify",
        ],
    )
    def test_reporter_paths_detected(self, path):
        """Reporter-facing paths must be identified correctly."""
        assert _is_reporter_endpoint(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/admin/cases",
            "/api/v1/admin/users",
            "/api/v1/health",
            "/api/v1/auth/oidc/callback",
            "/api/v1/dashboard",
            "/admin/",
        ],
    )
    def test_non_reporter_paths_ignored(self, path):
        """Non-reporter paths must not trigger anonymity protections."""
        assert _is_reporter_endpoint(path) is False


# ── Request Anonymisation (IP Stripping) ─────────────────────


class TestAnonymiseRequest:
    """Tests for ``_anonymise_request`` -- IP removal from request context."""

    @staticmethod
    def _make_scope(
        path: str = "/api/v1/reports",
        client: tuple[str, int] = ("192.168.1.100", 54321),
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> dict:
        """Build a minimal ASGI scope for testing."""
        if headers is None:
            headers = [
                (b"host", b"localhost"),
                (b"content-type", b"application/json"),
            ]
        return {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "client": client,
            "root_path": "",
        }

    def test_client_ip_replaced(self):
        """``request.scope['client']`` must be replaced with ``('0.0.0.0', 0)``."""
        scope = self._make_scope(client=("10.0.0.1", 12345))
        request = Request(scope)

        _anonymise_request(request)

        assert request.scope["client"] == _ANONYMOUS_CLIENT
        assert request.client.host == "0.0.0.0"
        assert request.client.port == 0

    def test_x_forwarded_for_stripped(self):
        """``X-Forwarded-For`` header must be removed."""
        headers = [
            (b"host", b"localhost"),
            (b"x-forwarded-for", b"203.0.113.50"),
            (b"content-type", b"application/json"),
        ]
        scope = self._make_scope(headers=headers)
        request = Request(scope)

        _anonymise_request(request)

        header_names = {name.decode() for name, _ in request.scope["headers"]}
        assert "x-forwarded-for" not in header_names

    def test_x_real_ip_stripped(self):
        """``X-Real-IP`` header must be removed."""
        headers = [
            (b"host", b"localhost"),
            (b"x-real-ip", b"198.51.100.25"),
        ]
        scope = self._make_scope(headers=headers)
        request = Request(scope)

        _anonymise_request(request)

        header_names = {name.decode() for name, _ in request.scope["headers"]}
        assert "x-real-ip" not in header_names

    def test_all_identifying_headers_stripped(self):
        """All headers in ``_IDENTIFYING_HEADERS`` must be stripped."""
        headers = [
            (b"host", b"localhost"),
            (b"x-forwarded-for", b"1.2.3.4"),
            (b"x-real-ip", b"5.6.7.8"),
            (b"x-client-ip", b"9.10.11.12"),
            (b"cf-connecting-ip", b"13.14.15.16"),
            (b"true-client-ip", b"17.18.19.20"),
            (b"forwarded", b"for=21.22.23.24"),
            (b"content-type", b"application/json"),
        ]
        scope = self._make_scope(headers=headers)
        request = Request(scope)

        _anonymise_request(request)

        remaining_names = {
            name.decode("latin-1").lower()
            for name, _ in request.scope["headers"]
        }
        for h in _IDENTIFYING_HEADERS:
            assert h not in remaining_names, f"Header '{h}' was not stripped"

    def test_non_identifying_headers_preserved(self):
        """Non-identifying headers like ``Host`` and ``Content-Type``
        must not be removed."""
        headers = [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"accept", b"*/*"),
            (b"x-forwarded-for", b"1.2.3.4"),
        ]
        scope = self._make_scope(headers=headers)
        request = Request(scope)

        _anonymise_request(request)

        remaining = {name.decode() for name, _ in request.scope["headers"]}
        assert "host" in remaining
        assert "content-type" in remaining
        assert "accept" in remaining

    def test_no_ip_in_request_context_after_anonymisation(self):
        """After anonymisation, there must be no way to recover the
        original IP from the request context."""
        real_ip = "203.0.113.99"
        headers = [
            (b"host", b"localhost"),
            (b"x-forwarded-for", b"203.0.113.99"),
            (b"x-real-ip", b"203.0.113.99"),
        ]
        scope = self._make_scope(client=(real_ip, 8080), headers=headers)
        request = Request(scope)

        _anonymise_request(request)

        # Check client address
        assert request.client.host != real_ip

        # Check no header contains the real IP
        for _, value in request.scope["headers"]:
            assert real_ip not in value.decode("latin-1")


# ── Response Anonymisation ───────────────────────────────────


class TestAnonymiseResponse:
    """Tests for ``_anonymise_response`` -- cookie stripping and cache headers."""

    def test_set_cookie_removed(self):
        """``Set-Cookie`` headers must be stripped from the response."""
        response = Response(content="ok")
        response.set_cookie("session", "abc123")
        response.set_cookie("tracking", "xyz789")

        _anonymise_response(response)

        # MutableHeaders wraps the raw scope; check the scope directly
        header_names = {
            name.decode("latin-1").lower()
            for name, _ in response.raw_headers
        }
        assert "set-cookie" not in header_names

    def test_cache_control_set(self):
        """Response must have ``Cache-Control: no-store, no-cache, must-revalidate``."""
        response = Response(content="ok")

        _anonymise_response(response)

        assert response.headers.get("cache-control") == (
            "no-store, no-cache, must-revalidate"
        )

    def test_pragma_set(self):
        """Response must have ``Pragma: no-cache``."""
        response = Response(content="ok")

        _anonymise_response(response)

        assert response.headers.get("pragma") == "no-cache"


# ── Response Time Padding ────────────────────────────────────


class TestResponseTimePadding:
    """Tests for the 200 ms minimum response time enforcement.

    These tests use the ``AnonymityMiddleware`` dispatch method
    with a mock ``call_next`` to verify timing behaviour.
    """

    @pytest.fixture()
    def middleware(self):
        """Create an ``AnonymityMiddleware`` instance."""
        # BaseHTTPMiddleware requires an app argument
        from starlette.applications import Starlette

        app = Starlette()
        return AnonymityMiddleware(app)

    @staticmethod
    def _make_request(path: str = "/api/v1/reports") -> Request:
        """Create a minimal ASGI Request for testing."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [
                (b"host", b"localhost"),
                (b"content-type", b"application/json"),
            ],
            "client": ("192.168.1.1", 12345),
            "root_path": "",
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_minimum_response_time_enforced(self, middleware):
        """Reporter endpoint responses must take at least 200 ms.

        Uses a tolerance of 20 ms to account for OS timer granularity
        (Windows has ~15.6 ms resolution for ``asyncio.sleep``).
        """
        request = self._make_request("/api/v1/reports")

        # Simulate a fast handler (~1ms)
        async def fast_handler(req):
            return Response(content="ok", status_code=200)

        start = time.monotonic()
        response = await middleware.dispatch(request, fast_handler)
        elapsed = time.monotonic() - start

        # Allow 20 ms tolerance for OS timer granularity (Windows ~15.6ms)
        assert elapsed >= _MIN_RESPONSE_TIME_SECONDS - 0.020
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_response_not_padded(self, middleware):
        """A response already exceeding 200 ms must not add extra delay."""
        request = self._make_request("/api/v1/reports")

        # Simulate a slow handler (300 ms)
        async def slow_handler(req):
            await asyncio.sleep(0.3)
            return Response(content="ok", status_code=200)

        start = time.monotonic()
        response = await middleware.dispatch(request, slow_handler)
        elapsed = time.monotonic() - start

        # Should not pad significantly beyond the actual handler time
        assert elapsed < 0.5  # Allow some overhead, but no extra 200ms
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_reporter_endpoint_not_padded(self, middleware):
        """Non-reporter endpoints must not have response time padding."""
        request = self._make_request("/api/v1/admin/cases")

        async def fast_handler(req):
            return Response(content="ok", status_code=200)

        start = time.monotonic()
        response = await middleware.dispatch(request, fast_handler)
        elapsed = time.monotonic() - start

        # Should complete very fast (no 200ms padding)
        assert elapsed < 0.1
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_padding_constant_is_200ms(self):
        """The minimum response time constant must be 200 ms."""
        assert _MIN_RESPONSE_TIME_SECONDS == 0.200


# ── Full Middleware Integration (IP + Cookies + Timing) ──────


class TestAnonymityMiddlewareIntegration:
    """Integration tests verifying all anonymity protections work together."""

    @pytest.fixture()
    def middleware(self):
        from starlette.applications import Starlette

        app = Starlette()
        return AnonymityMiddleware(app)

    @staticmethod
    def _make_request(
        path: str = "/api/v1/reports",
        headers: list[tuple[bytes, bytes]] | None = None,
        client: tuple[str, int] = ("10.0.0.1", 9999),
    ) -> Request:
        if headers is None:
            headers = [
                (b"host", b"localhost"),
                (b"x-forwarded-for", b"10.0.0.1"),
                (b"x-real-ip", b"10.0.0.1"),
            ]
        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "client": client,
            "root_path": "",
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_full_anonymity_on_reporter_endpoint(self, middleware):
        """Reporter endpoint must have IP stripped, cookies removed,
        cache headers set, and response time ≥ 200 ms."""
        request = self._make_request("/api/v1/reports/submit")

        async def handler(req):
            # Verify IP is stripped inside the handler
            assert req.client.host == "0.0.0.0"
            header_names = {
                name.decode("latin-1").lower()
                for name, _ in req.scope["headers"]
            }
            assert "x-forwarded-for" not in header_names
            assert "x-real-ip" not in header_names

            resp = Response(content="report submitted", status_code=201)
            resp.set_cookie("tracking", "should-be-removed")
            return resp

        start = time.monotonic()
        response = await middleware.dispatch(request, handler)
        elapsed = time.monotonic() - start

        # Timing
        assert elapsed >= _MIN_RESPONSE_TIME_SECONDS

        # Cookie stripped
        cookie_headers = {
            name.decode("latin-1").lower()
            for name, _ in response.raw_headers
            if name.decode("latin-1").lower() == "set-cookie"
        }
        assert "set-cookie" not in cookie_headers

        # Cache headers
        assert response.headers.get("cache-control") == (
            "no-store, no-cache, must-revalidate"
        )
        assert response.headers.get("pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_non_reporter_endpoint_passes_through(self, middleware):
        """Non-reporter endpoints must not have any anonymity protections."""
        headers = [
            (b"host", b"localhost"),
            (b"x-forwarded-for", b"10.0.0.1"),
        ]
        request = self._make_request(
            "/api/v1/admin/cases",
            headers=headers,
            client=("10.0.0.1", 9999),
        )

        async def handler(req):
            # IP should NOT be stripped for admin endpoints
            assert req.client.host == "10.0.0.1"
            return Response(content="ok")

        response = await middleware.dispatch(request, handler)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_reporter_prefixes_all_protected(self, middleware):
        """All configured reporter prefixes must trigger full protection."""
        for prefix in _REPORTER_PREFIXES:
            request = self._make_request(prefix + "/test")

            async def handler(req):
                assert req.client.host == "0.0.0.0", (
                    f"IP not stripped for {prefix}"
                )
                return Response(content="ok")

            await middleware.dispatch(request, handler)
