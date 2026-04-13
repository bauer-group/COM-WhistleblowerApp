"""Hinweisgebersystem -- Authentication & Authorization Tests.

Tests:
- bcrypt password hashing and verification (async thread-pool).
- Magic-link JWT creation, validation, and expiry behaviour.
- Magic-link JWT rejection of tampered / wrong-type tokens.
- RBAC endpoint access per role (all 5 roles).
- Role-to-scope mapping correctness.
- ``require_role`` dependency access control.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.security import (
    _ROLE_SCOPES,
    _role_to_scopes,
    create_magic_link_token,
    hash_password,
    verify_magic_link_token,
    verify_password,
)
from app.models.user import UserRole


# ── Password Hashing (bcrypt) ────────────────────────────────


class TestPasswordHashing:
    """Tests for ``hash_password`` / ``verify_password``."""

    @pytest.mark.asyncio
    async def test_hash_password_returns_string(self):
        """``hash_password`` must return a UTF-8 bcrypt hash string."""
        hashed = await hash_password("test-passphrase-123")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    @pytest.mark.asyncio
    async def test_verify_correct_password(self):
        """Correct password must verify successfully."""
        password = "mein-sicheres-passwort"
        hashed = await hash_password(password)

        result = await verify_password(password, hashed)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_wrong_password(self):
        """Incorrect password must fail verification."""
        hashed = await hash_password("correct-password")

        result = await verify_password("wrong-password", hashed)
        assert result is False

    @pytest.mark.asyncio
    async def test_hash_is_unique_per_call(self):
        """Same password must produce different hashes (unique salt)."""
        password = "same-password"
        h1 = await hash_password(password)
        h2 = await hash_password(password)
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_verify_both_hashes(self):
        """Both unique hashes of the same password must verify."""
        password = "both-valid"
        h1 = await hash_password(password)
        h2 = await hash_password(password)

        assert await verify_password(password, h1) is True
        assert await verify_password(password, h2) is True

    @pytest.mark.asyncio
    async def test_empty_password(self):
        """Empty string password must hash and verify correctly."""
        hashed = await hash_password("")
        assert await verify_password("", hashed) is True
        assert await verify_password("notempty", hashed) is False

    @pytest.mark.asyncio
    async def test_unicode_password(self):
        """Unicode passwords (German Umlaute) must hash and verify."""
        password = "Tr\u00e4ume-und-\u00dcberflieger-2024!"
        hashed = await hash_password(password)
        assert await verify_password(password, hashed) is True


# ── Magic-Link JWT ───────────────────────────────────────────


class TestMagicLinkToken:
    """Tests for ``create_magic_link_token`` / ``verify_magic_link_token``."""

    @pytest.fixture()
    def settings(self, test_settings) -> Settings:
        """Shortcut for test settings."""
        return test_settings

    @pytest.fixture()
    def report_id(self) -> uuid.UUID:
        return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def test_create_returns_string(self, settings, report_id):
        """Token must be a non-empty string."""
        token = create_magic_link_token(
            "reporter@example.com", report_id, settings=settings
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_round_trip_valid_token(self, settings, report_id):
        """Created token must decode successfully with correct payload."""
        email = "reporter@example.com"
        token = create_magic_link_token(email, report_id, settings=settings)
        payload = verify_magic_link_token(token, settings=settings)

        assert payload["sub"] == email
        assert payload["report_id"] == str(report_id)
        assert payload["type"] == "magic_link"

    def test_token_contains_required_claims(self, settings, report_id):
        """Token payload must include sub, report_id, exp, iat, type."""
        token = create_magic_link_token(
            "test@example.com", report_id, settings=settings
        )
        # Decode without verification to inspect claims
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        assert "sub" in payload
        assert "report_id" in payload
        assert "exp" in payload
        assert "iat" in payload
        assert payload["type"] == "magic_link"

    def test_token_expiry_time(self, settings, report_id):
        """Token expiry must match ``jwt_magic_link_expire_minutes``."""
        token = create_magic_link_token(
            "test@example.com", report_id, settings=settings
        )
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        delta = exp - iat
        assert delta == timedelta(minutes=settings.jwt_magic_link_expire_minutes)

    def test_expired_token_raises_401(self, settings, report_id):
        """An expired token must raise ``HTTPException`` with status 401."""
        # Create a token that expired 1 hour ago
        now = datetime.now(UTC)
        payload = {
            "sub": "expired@example.com",
            "report_id": str(report_id),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "type": "magic_link",
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_magic_link_token(token, settings=settings)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_tampered_token_raises_401(self, settings, report_id):
        """A token signed with a different secret must fail."""
        token = create_magic_link_token(
            "test@example.com", report_id, settings=settings
        )
        # Tamper: modify the last character
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        with pytest.raises(HTTPException) as exc_info:
            verify_magic_link_token(tampered, settings=settings)
        assert exc_info.value.status_code == 401

    def test_wrong_token_type_raises_401(self, settings, report_id):
        """A token with ``type != 'magic_link'`` must be rejected."""
        now = datetime.now(UTC)
        payload = {
            "sub": "test@example.com",
            "report_id": str(report_id),
            "iat": now,
            "exp": now + timedelta(hours=1),
            "type": "access_token",  # Wrong type
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_magic_link_token(token, settings=settings)
        assert exc_info.value.status_code == 401
        assert "token type" in exc_info.value.detail.lower()

    def test_missing_required_claim_raises_401(self, settings):
        """A token missing a required claim must be rejected."""
        now = datetime.now(UTC)
        payload = {
            "sub": "test@example.com",
            # Missing 'report_id'
            "iat": now,
            "exp": now + timedelta(hours=1),
            "type": "magic_link",
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_magic_link_token(token, settings=settings)
        assert exc_info.value.status_code == 401

    def test_completely_invalid_token_raises_401(self, settings):
        """A garbage string must raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_magic_link_token("not.a.valid.jwt", settings=settings)
        assert exc_info.value.status_code == 401

    def test_different_reports_produce_different_tokens(self, settings):
        """Tokens for different report IDs must differ."""
        email = "same@example.com"
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()

        t1 = create_magic_link_token(email, id1, settings=settings)
        t2 = create_magic_link_token(email, id2, settings=settings)

        assert t1 != t2


# ── Role-to-Scope Mapping ───────────────────────────────────


class TestRoleToScopes:
    """Tests for ``_role_to_scopes`` and the ``_ROLE_SCOPES`` mapping."""

    def test_all_roles_have_scopes(self):
        """Every ``UserRole`` must have a corresponding scope mapping."""
        for role in UserRole:
            scopes = _role_to_scopes(role)
            assert isinstance(scopes, set), f"{role} has no scope mapping"
            assert len(scopes) > 0, f"{role} has empty scope set"

    def test_system_admin_has_all_scopes(self):
        """System admin must have the widest permission set."""
        admin_scopes = _role_to_scopes(UserRole.SYSTEM_ADMIN)
        # System admin should have at least as many scopes as any other role
        for role in UserRole:
            role_scopes = _role_to_scopes(role)
            assert role_scopes.issubset(admin_scopes), (
                f"{role.value} has scopes not in system_admin: "
                f"{role_scopes - admin_scopes}"
            )

    def test_handler_can_read_and_write_cases(self):
        """Handler must have read+write access to cases."""
        scopes = _role_to_scopes(UserRole.HANDLER)
        assert "cases:read" in scopes
        assert "cases:write" in scopes

    def test_reviewer_is_read_only(self):
        """Reviewer must not have any write scopes."""
        scopes = _role_to_scopes(UserRole.REVIEWER)
        write_scopes = {s for s in scopes if ":write" in s or ":delete" in s}
        assert len(write_scopes) == 0, f"Reviewer has write scopes: {write_scopes}"

    def test_auditor_has_audit_read(self):
        """Auditor must have ``audit:read`` access."""
        scopes = _role_to_scopes(UserRole.AUDITOR)
        assert "audit:read" in scopes

    def test_auditor_cannot_write_cases(self):
        """Auditor must not be able to modify cases."""
        scopes = _role_to_scopes(UserRole.AUDITOR)
        assert "cases:write" not in scopes
        assert "cases:delete" not in scopes

    def test_tenant_admin_can_manage_users(self):
        """Tenant admin must have user management scopes."""
        scopes = _role_to_scopes(UserRole.TENANT_ADMIN)
        assert "users:read" in scopes
        assert "users:write" in scopes

    def test_handler_cannot_manage_users(self):
        """Handler must not have user management scopes."""
        scopes = _role_to_scopes(UserRole.HANDLER)
        assert "users:write" not in scopes

    def test_all_roles_have_dashboard_read(self):
        """Every role must be able to view the dashboard."""
        for role in UserRole:
            scopes = _role_to_scopes(role)
            assert "dashboard:read" in scopes, (
                f"{role.value} missing dashboard:read"
            )

    def test_scope_set_consistency(self):
        """Role scopes dict keys must match UserRole enum values."""
        role_values = {r.value for r in UserRole}
        scope_keys = set(_ROLE_SCOPES.keys())
        assert scope_keys == role_values, (
            f"Mismatch: roles={role_values}, scopes={scope_keys}"
        )


# ── RBAC Endpoint Access (require_role) ──────────────────────


class TestRequireRole:
    """Tests for the ``require_role`` dependency factory.

    These tests verify that ``require_role`` correctly gates access
    based on user roles without requiring a running FastAPI application.
    We mock the OIDC validation and database lookup to isolate the
    role-checking logic.
    """

    @pytest.fixture()
    def settings(self, test_settings) -> Settings:
        return test_settings

    @staticmethod
    def _make_credentials(token: str = "mock-bearer-token"):
        """Create a mock ``HTTPAuthorizationCredentials``."""
        creds = MagicMock()
        creds.credentials = token
        return creds

    @pytest.mark.asyncio
    async def test_allowed_role_passes(self, settings, make_user):
        """A user with an allowed role must pass the check."""
        from app.core.security import require_role

        handler = make_user(UserRole.HANDLER)
        checker = require_role(UserRole.HANDLER, UserRole.TENANT_ADMIN)

        with (
            patch(
                "app.core.security._validate_oidc_access_token",
                new_callable=AsyncMock,
                return_value={"sub": handler.oidc_subject},
            ),
            patch(
                "app.core.security.get_admin_session_factory"
            ) as mock_factory,
        ):
            # Mock the async session context manager and query result
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = handler
            mock_session.execute.return_value = mock_result

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_ctx)

            creds = self._make_credentials()
            result = await checker(credentials=creds, settings=settings)
            assert result.role == UserRole.HANDLER

    @pytest.mark.asyncio
    async def test_disallowed_role_raises_403(self, settings, make_user):
        """A user with a role not in the allowed set must get 403."""
        from app.core.security import require_role

        auditor = make_user(UserRole.AUDITOR)
        checker = require_role(UserRole.HANDLER, UserRole.TENANT_ADMIN)

        with (
            patch(
                "app.core.security._validate_oidc_access_token",
                new_callable=AsyncMock,
                return_value={"sub": auditor.oidc_subject},
            ),
            patch(
                "app.core.security.get_admin_session_factory"
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = auditor
            mock_session.execute.return_value = mock_result

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_ctx)

            creds = self._make_credentials()
            with pytest.raises(HTTPException) as exc_info:
                await checker(credentials=creds, settings=settings)
            assert exc_info.value.status_code == 403
            assert "role" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_inactive_user_raises_403(self, settings, make_user):
        """An inactive user must get 403 regardless of role."""
        from app.core.security import require_role

        inactive = make_user(UserRole.SYSTEM_ADMIN, is_active=False)
        checker = require_role(UserRole.SYSTEM_ADMIN)

        with (
            patch(
                "app.core.security._validate_oidc_access_token",
                new_callable=AsyncMock,
                return_value={"sub": inactive.oidc_subject},
            ),
            patch(
                "app.core.security.get_admin_session_factory"
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = inactive
            mock_session.execute.return_value = mock_result

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_ctx)

            creds = self._make_credentials()
            with pytest.raises(HTTPException) as exc_info:
                await checker(credentials=creds, settings=settings)
            assert exc_info.value.status_code == 403
            assert "deactivated" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_unknown_user_raises_401(self, settings):
        """A valid OIDC token for an unknown user must get 401."""
        from app.core.security import require_role

        checker = require_role(UserRole.HANDLER)

        with (
            patch(
                "app.core.security._validate_oidc_access_token",
                new_callable=AsyncMock,
                return_value={"sub": "unknown-oidc-subject"},
            ),
            patch(
                "app.core.security.get_admin_session_factory"
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute.return_value = mock_result

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_ctx)

            creds = self._make_credentials()
            with pytest.raises(HTTPException) as exc_info:
                await checker(credentials=creds, settings=settings)
            assert exc_info.value.status_code == 401
            assert "not registered" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self, settings):
        """Missing bearer token must raise 401."""
        from app.core.security import require_role

        checker = require_role(UserRole.HANDLER)
        with pytest.raises(HTTPException) as exc_info:
            await checker(credentials=None, settings=settings)
        assert exc_info.value.status_code == 401
        assert "not authenticated" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", list(UserRole))
    async def test_each_role_can_access_own_role_endpoint(
        self, settings, make_user, role
    ):
        """Each of the 5 roles must be able to access an endpoint
        restricted to that role."""
        from app.core.security import require_role

        user = make_user(role)
        checker = require_role(role)

        with (
            patch(
                "app.core.security._validate_oidc_access_token",
                new_callable=AsyncMock,
                return_value={"sub": user.oidc_subject},
            ),
            patch(
                "app.core.security.get_admin_session_factory"
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = user
            mock_session.execute.return_value = mock_result

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = None
            mock_factory.return_value = MagicMock(return_value=mock_ctx)

            creds = self._make_credentials()
            result = await checker(credentials=creds, settings=settings)
            assert result.role == role

    @pytest.mark.asyncio
    async def test_missing_sub_claim_raises_401(self, settings):
        """A token payload without 'sub' must raise 401."""
        from app.core.security import require_role

        checker = require_role(UserRole.HANDLER)

        with patch(
            "app.core.security._validate_oidc_access_token",
            new_callable=AsyncMock,
            return_value={"email": "no-sub@example.com"},  # missing 'sub'
        ):
            creds = self._make_credentials()
            with pytest.raises(HTTPException) as exc_info:
                await checker(credentials=creds, settings=settings)
            assert exc_info.value.status_code == 401
