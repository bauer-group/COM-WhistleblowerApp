"""Hinweisgebersystem -- Anti-Forensics Middleware Tests.

Tests:
- Cache-Control: no-store on all responses.
- X-Content-Type-Options: nosniff on all responses.
- Referrer-Policy: no-referrer on all responses.
- Clear-Site-Data header on logout endpoint only.
- Clear-Site-Data header NOT present on non-logout endpoints.
- AnonymityMiddleware enhanced headers on reporter endpoints.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.anonymity import (
    AntiForensicsMiddleware,
    AnonymityMiddleware,
    _LOGOUT_PATHS,
)


# ── Test Fixtures ───────────────────────────────────────────


@pytest.fixture()
def anti_forensics_middleware():
    """Create an ``AntiForensicsMiddleware`` instance."""
    app = Starlette()
    return AntiForensicsMiddleware(app)


@pytest.fixture()
def anonymity_middleware():
    """Create an ``AnonymityMiddleware`` instance."""
    app = Starlette()
    return AnonymityMiddleware(app)


def _make_request(path: str = "/api/v1/admin/cases") -> Request:
    """Create a minimal ASGI Request for testing."""
    scope = {
        "type": "http",
        "method": "GET",
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


async def _ok_handler(request: Request) -> Response:
    """Simple handler returning a 200 OK response."""
    return Response(content="ok", status_code=200)


# ── Anti-Forensics Headers on All Responses ──────────────────


class TestAntiForensicsHeaders:
    """Tests for browser anti-forensics headers on ALL responses."""

    @pytest.mark.asyncio
    async def test_cache_control_no_store(self, anti_forensics_middleware):
        """All responses must have ``Cache-Control: no-store``."""
        request = _make_request("/api/v1/admin/cases")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)
        assert response.headers.get("cache-control") == "no-store"

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self, anti_forensics_middleware):
        """All responses must have ``X-Content-Type-Options: nosniff``."""
        request = _make_request("/api/v1/admin/cases")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)
        assert response.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_referrer_policy_no_referrer(self, anti_forensics_middleware):
        """All responses must have ``Referrer-Policy: no-referrer``."""
        request = _make_request("/api/v1/admin/cases")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)
        assert response.headers.get("referrer-policy") == "no-referrer"

    @pytest.mark.asyncio
    async def test_headers_on_various_endpoints(self, anti_forensics_middleware):
        """Anti-forensics headers must be present on diverse endpoints."""
        paths = [
            "/api/v1/admin/cases",
            "/api/v1/admin/users",
            "/api/v1/health",
            "/api/v1/reports",
            "/api/v1/dashboard",
            "/",
        ]
        for path in paths:
            request = _make_request(path)
            response = await anti_forensics_middleware.dispatch(request, _ok_handler)
            assert response.headers.get("cache-control") == "no-store", (
                f"Missing Cache-Control on {path}"
            )
            assert response.headers.get("x-content-type-options") == "nosniff", (
                f"Missing X-Content-Type-Options on {path}"
            )
            assert response.headers.get("referrer-policy") == "no-referrer", (
                f"Missing Referrer-Policy on {path}"
            )

    @pytest.mark.asyncio
    async def test_headers_on_error_response(self, anti_forensics_middleware):
        """Anti-forensics headers must also be present on error responses."""
        async def error_handler(request):
            return Response(content="error", status_code=500)

        request = _make_request("/api/v1/admin/cases")
        response = await anti_forensics_middleware.dispatch(request, error_handler)

        assert response.headers.get("cache-control") == "no-store"
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") == "no-referrer"


# ── Clear-Site-Data on Logout Only ───────────────────────────


class TestClearSiteDataOnLogout:
    """Tests for Clear-Site-Data header (logout-only)."""

    @pytest.mark.asyncio
    async def test_clear_site_data_on_logout(self, anti_forensics_middleware):
        """Logout endpoint must have Clear-Site-Data header."""
        request = _make_request("/api/v1/auth/logout")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)

        clear_header = response.headers.get("clear-site-data")
        assert clear_header is not None
        assert "cache" in clear_header
        assert "cookies" in clear_header
        assert "storage" in clear_header

    @pytest.mark.asyncio
    async def test_no_clear_site_data_on_admin_endpoint(
        self, anti_forensics_middleware
    ):
        """Non-logout endpoints must NOT have Clear-Site-Data header."""
        request = _make_request("/api/v1/admin/cases")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)

        assert response.headers.get("clear-site-data") is None

    @pytest.mark.asyncio
    async def test_no_clear_site_data_on_health(self, anti_forensics_middleware):
        """Health endpoint must NOT have Clear-Site-Data header."""
        request = _make_request("/api/v1/health")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)

        assert response.headers.get("clear-site-data") is None

    @pytest.mark.asyncio
    async def test_no_clear_site_data_on_login(self, anti_forensics_middleware):
        """Login endpoint must NOT have Clear-Site-Data header."""
        request = _make_request("/api/v1/auth/oidc/login")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)

        assert response.headers.get("clear-site-data") is None

    @pytest.mark.asyncio
    async def test_no_clear_site_data_on_reporter(self, anti_forensics_middleware):
        """Reporter endpoints must NOT have Clear-Site-Data header."""
        request = _make_request("/api/v1/reports/submit")
        response = await anti_forensics_middleware.dispatch(request, _ok_handler)

        assert response.headers.get("clear-site-data") is None

    @pytest.mark.asyncio
    async def test_logout_paths_config(self):
        """Verify the logout paths configuration is correct."""
        assert "/api/v1/auth/logout" in _LOGOUT_PATHS


# ── AnonymityMiddleware Enhanced Headers ─────────────────────


class TestAnonymityMiddlewareHeaders:
    """Tests for enhanced cache headers on reporter endpoints.

    The ``AnonymityMiddleware`` applies additional anti-caching headers
    (``Cache-Control: no-store, no-cache, must-revalidate`` and
    ``Pragma: no-cache``) specifically to reporter-facing endpoints.
    """

    @pytest.mark.asyncio
    async def test_reporter_enhanced_cache_control(self, anonymity_middleware):
        """Reporter endpoints must have enhanced Cache-Control header."""
        request = _make_request("/api/v1/public/complaints")
        response = await anonymity_middleware.dispatch(request, _ok_handler)

        cc = response.headers.get("cache-control")
        assert cc is not None
        assert "no-store" in cc
        assert "no-cache" in cc
        assert "must-revalidate" in cc

    @pytest.mark.asyncio
    async def test_reporter_pragma_no_cache(self, anonymity_middleware):
        """Reporter endpoints must have ``Pragma: no-cache``."""
        request = _make_request("/api/v1/public/complaints")
        response = await anonymity_middleware.dispatch(request, _ok_handler)

        assert response.headers.get("pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_non_reporter_no_enhanced_headers(self, anonymity_middleware):
        """Non-reporter endpoints must NOT get enhanced cache headers
        from AnonymityMiddleware (they still get basic headers from
        AntiForensicsMiddleware, which is a separate middleware layer).
        """
        request = _make_request("/api/v1/admin/cases")
        response = await anonymity_middleware.dispatch(request, _ok_handler)

        # AnonymityMiddleware does not add headers to non-reporter paths
        # (AntiForensicsMiddleware adds the base headers)
        cc = response.headers.get("cache-control")
        # The response passes through unmodified for non-reporter endpoints
        # so cache-control should NOT contain "must-revalidate"
        if cc:
            assert "must-revalidate" not in cc
