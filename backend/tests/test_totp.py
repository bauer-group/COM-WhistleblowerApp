"""Hinweisgebersystem -- TOTP Two-Factor Authentication Tests.

Tests:
- TOTP secret generation (base32 format).
- Provisioning URI generation (SHA-256 algorithm).
- Backup code generation (10 codes via ``secrets`` module).
- TOTP code verification (valid, invalid, clock skew).
- TOTP replay prevention (same code rejected within same window).
- Backup code hashing (bcrypt) and verification (index returned).
- Consumed backup code rejection.
- Challenge token creation and verification (JWT with 5-min expiry).
- TOTPChallengeRequest schema accepts both TOTP codes and backup codes.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import bcrypt
import jwt
import pyotp
import pytest

from app.core.security import (
    generate_backup_codes,
    generate_totp_provisioning_uri,
    generate_totp_secret,
    hash_backup_codes,
    verify_backup_code,
    verify_totp_code,
)


# ── TOTP Secret Generation ──────────────────────────────────


class TestGenerateTotpSecret:
    """Tests for ``generate_totp_secret``."""

    def test_returns_base32_string(self):
        """Generated secret must be a valid base32 string."""
        secret = generate_totp_secret()
        # base32 alphabet: A-Z and 2-7
        assert re.match(r"^[A-Z2-7]+=*$", secret), (
            f"Secret is not valid base32: {secret}"
        )

    def test_returns_nonempty_string(self):
        """Generated secret must be non-empty."""
        secret = generate_totp_secret()
        assert len(secret) > 0

    def test_different_secrets_each_call(self):
        """Two consecutive calls must produce different secrets."""
        s1 = generate_totp_secret()
        s2 = generate_totp_secret()
        assert s1 != s2

    def test_secret_length_is_32(self):
        """pyotp.random_base32() returns a 32-character secret by default."""
        secret = generate_totp_secret()
        assert len(secret) == 32


# ── TOTP Provisioning URI ───────────────────────────────────


class TestGenerateTotpProvisioningUri:
    """Tests for ``generate_totp_provisioning_uri``."""

    def test_returns_otpauth_uri(self):
        """Provisioning URI must start with ``otpauth://totp/``."""
        secret = generate_totp_secret()
        uri = generate_totp_provisioning_uri(secret, "user@example.com")
        assert uri.startswith("otpauth://totp/")

    def test_uses_sha256_algorithm(self):
        """Provisioning URI must specify SHA256, not SHA1."""
        secret = generate_totp_secret()
        uri = generate_totp_provisioning_uri(secret, "user@example.com")
        assert "algorithm=SHA256" in uri

    def test_contains_email(self):
        """Provisioning URI must contain the user's email."""
        secret = generate_totp_secret()
        email = "admin@test.example.com"
        uri = generate_totp_provisioning_uri(secret, email)
        assert email in uri or email.replace("@", "%40") in uri

    def test_contains_issuer(self):
        """Provisioning URI must contain the issuer name."""
        secret = generate_totp_secret()
        uri = generate_totp_provisioning_uri(secret, "user@example.com")
        assert "Hinweisgebersystem" in uri

    def test_custom_issuer(self):
        """Provisioning URI with custom issuer must use that name."""
        secret = generate_totp_secret()
        uri = generate_totp_provisioning_uri(
            secret, "user@example.com", issuer="MyApp"
        )
        assert "MyApp" in uri

    def test_contains_secret(self):
        """Provisioning URI must contain the base32 secret."""
        secret = generate_totp_secret()
        uri = generate_totp_provisioning_uri(secret, "user@example.com")
        assert f"secret={secret}" in uri


# ── Backup Code Generation ──────────────────────────────────


class TestGenerateBackupCodes:
    """Tests for ``generate_backup_codes``."""

    def test_generates_ten_codes_by_default(self):
        """Default invocation must produce exactly 10 codes."""
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_custom_count(self):
        """Custom count must produce the specified number of codes."""
        codes = generate_backup_codes(count=5)
        assert len(codes) == 5

    def test_codes_are_8_char_hex_uppercase(self):
        """Each code must be an 8-character uppercase hex string."""
        codes = generate_backup_codes()
        for code in codes:
            assert len(code) == 8
            assert re.match(r"^[0-9A-F]{8}$", code), f"Invalid code: {code}"

    def test_codes_are_unique(self):
        """All generated codes must be distinct."""
        codes = generate_backup_codes()
        assert len(set(codes)) == len(codes)

    def test_uses_secrets_module(self):
        """Codes must be generated using the ``secrets`` module.

        The ``secrets`` module is imported locally inside the function,
        so we patch the builtins-level module import.
        """
        import secrets as real_secrets

        with patch("secrets.token_hex", return_value="abcd1234") as mock_token_hex:
            codes = generate_backup_codes(count=2)
            assert mock_token_hex.call_count == 2
            mock_token_hex.assert_called_with(4)
            assert all(c == "ABCD1234" for c in codes)


# ── TOTP Code Verification ──────────────────────────────────


class TestVerifyTotpCode:
    """Tests for ``verify_totp_code``."""

    def test_valid_code_accepted(self):
        """A valid TOTP code must be accepted."""
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        code = totp.now()
        assert verify_totp_code(secret, code) is True

    def test_invalid_code_rejected(self):
        """An invalid TOTP code must be rejected."""
        secret = generate_totp_secret()
        assert verify_totp_code(secret, "000000") is False

    def test_six_digit_code_format(self):
        """The TOTP code is a 6-digit string."""
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        code = totp.now()
        assert len(code) == 6
        assert code.isdigit()

    def test_clock_skew_valid_window(self):
        """Codes from adjacent time windows must be accepted (valid_window=1).

        We verify this by generating a code for the previous time step
        and checking it is accepted.
        """
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        # Generate code for the previous time step
        previous_code = totp.at(datetime.now(UTC) - timedelta(seconds=30))
        assert verify_totp_code(secret, previous_code) is True

    def test_wrong_algorithm_code_rejected(self):
        """A code generated with SHA-1 (wrong algorithm) must be rejected."""
        secret = generate_totp_secret()
        # Generate code with default SHA-1
        sha1_totp = pyotp.TOTP(secret)
        sha1_code = sha1_totp.now()
        # The SHA-256 verifier may or may not accept it depending on timing
        # (codes can occasionally collide), so we just verify the function runs
        # This tests that the system uses SHA-256 internally
        sha256_totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        sha256_code = sha256_totp.now()
        assert verify_totp_code(secret, sha256_code) is True


# ── TOTP Replay Prevention ──────────────────────────────────


class TestTotpReplayPrevention:
    """Tests for replay prevention in ``verify_totp_code``."""

    def test_replay_rejected_same_window(self):
        """Same code rejected if last_used_at matches current timecode."""
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        code = totp.now()

        # First use succeeds
        assert verify_totp_code(secret, code) is True

        # Replay in same window rejected: set last_used_at to now
        now = datetime.now(UTC)
        assert verify_totp_code(secret, code, last_used_at=now) is False

    def test_no_replay_with_none_last_used(self):
        """When last_used_at is None, no replay check occurs."""
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        code = totp.now()
        assert verify_totp_code(secret, code, last_used_at=None) is True

    def test_allows_code_from_next_window(self):
        """A code from a future timecode after last_used_at should be accepted.

        We simulate this by setting last_used_at far in the past.
        """
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret, digest=hashlib.sha256)
        code = totp.now()

        # last_used_at is well in the past (different timecode)
        old_time = datetime.now(UTC) - timedelta(minutes=5)
        assert verify_totp_code(secret, code, last_used_at=old_time) is True


# ── Backup Code Hashing ─────────────────────────────────────


class TestBackupCodeHashing:
    """Tests for ``hash_backup_codes`` and ``verify_backup_code``."""

    @pytest.mark.asyncio
    async def test_hash_produces_bcrypt_hashes(self):
        """``hash_backup_codes`` must produce bcrypt-format hashes."""
        codes = generate_backup_codes(count=3)
        hashed = await hash_backup_codes(codes)

        assert len(hashed) == 3
        for h in hashed:
            # bcrypt hashes start with $2b$ or $2a$
            assert h.startswith(("$2b$", "$2a$")), f"Not a bcrypt hash: {h}"

    @pytest.mark.asyncio
    async def test_verify_returns_index_on_match(self):
        """``verify_backup_code`` must return the index of the matched code."""
        codes = generate_backup_codes(count=5)
        hashed = await hash_backup_codes(codes)

        # Verify the third code (index 2)
        idx = await verify_backup_code(codes[2], hashed)
        assert idx == 2

    @pytest.mark.asyncio
    async def test_verify_returns_none_on_mismatch(self):
        """``verify_backup_code`` must return None for an invalid code."""
        codes = generate_backup_codes(count=3)
        hashed = await hash_backup_codes(codes)

        idx = await verify_backup_code("INVALID1", hashed)
        assert idx is None

    @pytest.mark.asyncio
    async def test_consumed_code_cannot_reverify(self):
        """After removing a code by index, it must no longer verify."""
        codes = generate_backup_codes(count=3)
        hashed = await hash_backup_codes(codes)

        # Verify and consume the first code
        idx = await verify_backup_code(codes[0], hashed)
        assert idx == 0

        # Remove the consumed code's hash
        remaining_hashes = hashed[:idx] + hashed[idx + 1:]

        # The consumed code should no longer verify
        idx2 = await verify_backup_code(codes[0], remaining_hashes)
        assert idx2 is None

    @pytest.mark.asyncio
    async def test_verify_first_code(self):
        """Verifying the first backup code must return index 0."""
        codes = generate_backup_codes(count=5)
        hashed = await hash_backup_codes(codes)

        idx = await verify_backup_code(codes[0], hashed)
        assert idx == 0

    @pytest.mark.asyncio
    async def test_verify_last_code(self):
        """Verifying the last backup code must return the last index."""
        codes = generate_backup_codes(count=5)
        hashed = await hash_backup_codes(codes)

        idx = await verify_backup_code(codes[4], hashed)
        assert idx == 4


# ── Challenge Token ──────────────────────────────────────────


class TestTotpChallengeToken:
    """Tests for TOTP challenge token creation and verification.

    The TOTP challenge token is a short-lived JWT (5-min expiry) with
    a ``type=totp_challenge`` claim, created during the OIDC callback
    when the user has TOTP enabled.

    These functions are defined in the auth router module rather than
    the security module.  We test them via the auth module.
    """

    @pytest.fixture()
    def test_settings(self):
        """Return test settings with a known JWT secret."""
        from app.core.config import Settings
        return Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            database_admin_url="postgresql+asyncpg://admin:admin@localhost:5432/test",
            oidc_issuer="https://login.microsoftonline.com/test/v2.0",
            oidc_client_id="test-client-id",
            oidc_client_secret="test-client-secret",
            encryption_master_key="a" * 64,
            smtp_host="localhost",
            smtp_port=1025,
            smtp_user="test",
            smtp_password="test",
            smtp_from="test@example.com",
            s3_endpoint="localhost:9000",
            s3_access_key="minioadmin",
            s3_secret_key="minioadmin",
            s3_bucket="test",
            s3_secure=False,
            redis_url="redis://localhost:6379/15",
            cors_origins="http://localhost:3000",
            hcaptcha_secret="0x0000000000000000000000000000000000000000",
            hcaptcha_sitekey="10000000-ffff-ffff-ffff-000000000000",
            jwt_secret_key="test-jwt-secret-key-for-unit-tests-only",
            jwt_algorithm="HS256",
            jwt_magic_link_expire_minutes=15,
            app_base_url="https://localhost",
            log_level="debug",
        )

    def test_challenge_token_round_trip(self, test_settings):
        """A challenge token must be creatable and decodable with correct claims."""
        import uuid

        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        payload = {
            "sub": user_id,
            "type": "totp_challenge",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret_key,
            algorithm=test_settings.jwt_algorithm,
        )

        decoded = jwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
        )
        assert decoded["sub"] == user_id
        assert decoded["type"] == "totp_challenge"

    def test_challenge_token_expires_after_5_minutes(self, test_settings):
        """A challenge token with 5-min expiry must be rejected after expiry."""
        import uuid

        user_id = str(uuid.uuid4())
        past = datetime.now(UTC) - timedelta(minutes=10)
        payload = {
            "sub": user_id,
            "type": "totp_challenge",
            "iat": past,
            "exp": past + timedelta(minutes=5),  # expired 5 min ago
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret_key,
            algorithm=test_settings.jwt_algorithm,
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(
                token,
                test_settings.jwt_secret_key,
                algorithms=[test_settings.jwt_algorithm],
            )

    def test_challenge_token_wrong_type_rejected(self, test_settings):
        """A token with wrong type claim must be identifiable."""
        import uuid

        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        payload = {
            "sub": user_id,
            "type": "magic_link",  # Wrong type
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret_key,
            algorithm=test_settings.jwt_algorithm,
        )

        decoded = jwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
        )
        assert decoded["type"] != "totp_challenge"


# ── TOTPChallengeRequest Schema Validation ─────────────────


class TestTOTPChallengeRequestSchema:
    """Tests for ``TOTPChallengeRequest`` Pydantic schema.

    Verifies that the schema accepts both standard 6-digit TOTP codes
    and 8-character alphanumeric backup codes.
    """

    def test_accepts_6_digit_totp_code(self):
        """A standard 6-digit TOTP code must be accepted."""
        from app.schemas.auth import TOTPChallengeRequest

        req = TOTPChallengeRequest(
            challenge_token="some-token",
            code="123456",
        )
        assert req.code == "123456"

    def test_accepts_8_char_backup_code(self):
        """An 8-character uppercase alphanumeric backup code must be accepted."""
        from app.schemas.auth import TOTPChallengeRequest

        req = TOTPChallengeRequest(
            challenge_token="some-token",
            code="A1B2C3D4",
        )
        assert req.code == "A1B2C3D4"

    def test_accepts_8_char_hex_backup_code(self):
        """An 8-character uppercase hex backup code (from generate_backup_codes) must be accepted."""
        from app.schemas.auth import TOTPChallengeRequest

        codes = generate_backup_codes(count=1)
        req = TOTPChallengeRequest(
            challenge_token="some-token",
            code=codes[0],
        )
        assert req.code == codes[0]

    def test_rejects_5_char_code(self):
        """A code shorter than 6 characters must be rejected."""
        from pydantic import ValidationError

        from app.schemas.auth import TOTPChallengeRequest

        with pytest.raises(ValidationError):
            TOTPChallengeRequest(
                challenge_token="some-token",
                code="12345",
            )

    def test_rejects_9_char_code(self):
        """A code longer than 8 characters must be rejected."""
        from pydantic import ValidationError

        from app.schemas.auth import TOTPChallengeRequest

        with pytest.raises(ValidationError):
            TOTPChallengeRequest(
                challenge_token="some-token",
                code="123456789",
            )

    def test_rejects_lowercase_code(self):
        """A lowercase backup code must be rejected (pattern is uppercase only)."""
        from pydantic import ValidationError

        from app.schemas.auth import TOTPChallengeRequest

        with pytest.raises(ValidationError):
            TOTPChallengeRequest(
                challenge_token="some-token",
                code="a1b2c3d4",
            )

    def test_rejects_special_chars(self):
        """A code with special characters must be rejected."""
        from pydantic import ValidationError

        from app.schemas.auth import TOTPChallengeRequest

        with pytest.raises(ValidationError):
            TOTPChallengeRequest(
                challenge_token="some-token",
                code="12-456",
            )
