"""Hinweisgebersystem -- PGP Email Encryption Tests.

Tests:
- PGP key validation (valid ASCII-armored key accepted).
- Invalid key format rejection.
- Private key rejection with clear error message.
- Expired key rejection on import.
- Key expiry checking (is_key_expired).
- Email body encryption (encrypt_message).
- Fail-open policy (_maybe_pgp_encrypt returns None on errors).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.pgp_service import (
    PGPEncryptionError,
    PGPKeyExpiredError,
    PGPKeyImportError,
    PGPKeyInfo,
    PGPService,
)


# ── Test Fixtures ───────────────────────────────────────────


@pytest.fixture()
def mock_gpg():
    """Create a mocked gnupg.GPG instance."""
    gpg = MagicMock()
    gpg.encoding = "utf-8"
    return gpg


@pytest.fixture()
def pgp_service(mock_gpg, tmp_path):
    """Create a PGPService with a mocked GPG backend."""
    with patch("app.services.pgp_service.gnupg.GPG", return_value=mock_gpg):
        service = PGPService(keyring_path=str(tmp_path / ".gnupg-test"))
    service._gpg = mock_gpg
    return service


# ── PGP Key Validation ──────────────────────────────────────


class TestPGPKeyImport:
    """Tests for PGP key import and validation."""

    def test_valid_key_accepted(self, pgp_service, mock_gpg):
        """A valid ASCII-armored public key must return a PGPKeyInfo."""
        mock_gpg.import_keys.return_value = MagicMock(
            fingerprints=["ABCDEF1234567890ABCDEF1234567890ABCDEF12"]
        )
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                "expires": "",
                "uids": ["Test User <test@example.com>"],
            }
        ]

        armored_key = (
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
            "mocked key data\n"
            "-----END PGP PUBLIC KEY BLOCK-----"
        )

        key_info = pgp_service.import_key(armored_key)

        assert isinstance(key_info, PGPKeyInfo)
        assert key_info.fingerprint == "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        assert key_info.expires_at is None  # No expiry
        assert "Test User <test@example.com>" in key_info.user_ids

    def test_invalid_format_rejected(self, pgp_service):
        """A key without proper PGP header must be rejected."""
        with pytest.raises(PGPKeyImportError, match="Invalid key format"):
            pgp_service.import_key("this is not a PGP key")

    def test_private_key_rejected(self, pgp_service):
        """A private key must be rejected with a clear error message."""
        armored = (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "mocked private key data\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        )
        with pytest.raises(PGPKeyImportError, match="Private keys must not be uploaded"):
            pgp_service.import_key(armored)

    def test_private_key_case_insensitive(self, pgp_service):
        """Private key detection must be case-insensitive."""
        armored = (
            "-----BEGIN PGP private key BLOCK-----\n"
            "data\n"
            "-----END PGP private key BLOCK-----"
        )
        with pytest.raises(PGPKeyImportError, match="Private keys"):
            pgp_service.import_key(armored)

    def test_import_failure_raises_error(self, pgp_service, mock_gpg):
        """If GPG import returns no fingerprints, must raise error."""
        mock_gpg.import_keys.return_value = MagicMock(
            fingerprints=[], results=[{"status": "error"}]
        )

        armored = (
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
            "corrupt data\n"
            "-----END PGP PUBLIC KEY BLOCK-----"
        )
        with pytest.raises(PGPKeyImportError, match="Failed to import"):
            pgp_service.import_key(armored)


# ── PGP Key Expiry ──────────────────────────────────────────


class TestPGPKeyExpiry:
    """Tests for PGP key expiry checking."""

    def test_expired_key_rejected_on_import(self, pgp_service, mock_gpg):
        """An expired key must be rejected during import."""
        # Expire timestamp in the past
        past_ts = str(int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp()))

        mock_gpg.import_keys.return_value = MagicMock(
            fingerprints=["ABCDEF1234567890ABCDEF1234567890ABCDEF12"]
        )
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                "expires": past_ts,
                "uids": ["Test <test@example.com>"],
            }
        ]
        mock_gpg.delete_keys.return_value = "ok"

        armored = (
            "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
            "data\n"
            "-----END PGP PUBLIC KEY BLOCK-----"
        )

        with pytest.raises(PGPKeyImportError, match="already expired"):
            pgp_service.import_key(armored)

    def test_is_key_expired_returns_true_for_expired(self, pgp_service, mock_gpg):
        """``is_key_expired`` must return True for an expired fingerprint."""
        past_ts = str(int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "AAAA",
                "expires": past_ts,
                "uids": [],
            }
        ]
        assert pgp_service.is_key_expired("AAAA") is True

    def test_is_key_expired_returns_false_for_valid(self, pgp_service, mock_gpg):
        """``is_key_expired`` must return False for a valid (not expired) key."""
        future_ts = str(int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "BBBB",
                "expires": future_ts,
                "uids": [],
            }
        ]
        assert pgp_service.is_key_expired("BBBB") is False

    def test_is_key_expired_returns_false_for_no_expiry(self, pgp_service, mock_gpg):
        """A key without an expiry date must be treated as not expired."""
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "CCCC",
                "expires": "",
                "uids": [],
            }
        ]
        assert pgp_service.is_key_expired("CCCC") is False

    def test_is_key_expired_returns_true_for_missing_key(self, pgp_service, mock_gpg):
        """A key not found in the keyring must be treated as expired."""
        mock_gpg.list_keys.return_value = []
        assert pgp_service.is_key_expired("NONEXISTENT") is True


# ── PGP Email Encryption ────────────────────────────────────


class TestPGPEncryptMessage:
    """Tests for PGP email body encryption."""

    def test_encrypt_returns_encrypted_text(self, pgp_service, mock_gpg):
        """``encrypt_message`` must return encrypted text for a valid fingerprint."""
        future_ts = str(int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "AAAA",
                "expires": future_ts,
                "uids": [],
            }
        ]

        encrypted_mock = MagicMock()
        encrypted_mock.ok = True
        encrypted_mock.__str__ = lambda self: (
            "-----BEGIN PGP MESSAGE-----\nencrypted data\n"
            "-----END PGP MESSAGE-----"
        )
        mock_gpg.encrypt.return_value = encrypted_mock

        result = pgp_service.encrypt_message("Hello, world!", "AAAA")
        assert "BEGIN PGP MESSAGE" in result

    def test_encrypt_raises_on_expired_key(self, pgp_service, mock_gpg):
        """``encrypt_message`` must raise PGPKeyExpiredError for expired key."""
        past_ts = str(int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "EXPIRED",
                "expires": past_ts,
                "uids": [],
            }
        ]

        with pytest.raises(PGPKeyExpiredError, match="expired"):
            pgp_service.encrypt_message("Hello!", "EXPIRED")

    def test_encrypt_raises_on_gpg_failure(self, pgp_service, mock_gpg):
        """``encrypt_message`` must raise PGPEncryptionError when GPG fails."""
        future_ts = str(int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "VALID",
                "expires": future_ts,
                "uids": [],
            }
        ]

        encrypted_mock = MagicMock()
        encrypted_mock.ok = False
        encrypted_mock.status = "encryption failed"
        encrypted_mock.stderr = "some error"
        mock_gpg.encrypt.return_value = encrypted_mock

        with pytest.raises(PGPEncryptionError, match="encryption failed"):
            pgp_service.encrypt_message("Hello!", "VALID")

    def test_encrypt_passes_always_trust(self, pgp_service, mock_gpg):
        """``encrypt_message`` must pass always_trust=True to GPG."""
        future_ts = str(int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp()))
        mock_gpg.list_keys.return_value = [
            {
                "fingerprint": "TRUST",
                "expires": future_ts,
                "uids": [],
            }
        ]

        encrypted_mock = MagicMock()
        encrypted_mock.ok = True
        encrypted_mock.__str__ = lambda self: "encrypted"
        mock_gpg.encrypt.return_value = encrypted_mock

        pgp_service.encrypt_message("Hello!", "TRUST")

        mock_gpg.encrypt.assert_called_once_with(
            "Hello!",
            "TRUST",
            always_trust=True,
            armor=True,
        )


# ── PGP Fail-Open Policy ────────────────────────────────────


class TestMaybePGPEncrypt:
    """Tests for ``_maybe_pgp_encrypt`` fail-open behaviour."""

    def test_returns_none_when_no_fingerprint(self):
        """``_maybe_pgp_encrypt`` must return None when no fingerprint provided."""
        from app.core.smtp import _maybe_pgp_encrypt

        result = _maybe_pgp_encrypt(html_body="<p>Hello</p>", pgp_fingerprint=None)
        assert result is None

    def test_returns_none_when_empty_fingerprint(self):
        """``_maybe_pgp_encrypt`` must return None when fingerprint is empty."""
        from app.core.smtp import _maybe_pgp_encrypt

        result = _maybe_pgp_encrypt(html_body="<p>Hello</p>", pgp_fingerprint="")
        assert result is None

    def test_returns_none_on_expired_key(self):
        """``_maybe_pgp_encrypt`` must return None (fallback) when key is expired."""
        from app.core.smtp import _maybe_pgp_encrypt

        with patch("app.services.pgp_service.get_pgp_service") as mock_get:
            mock_service = MagicMock()
            mock_service.is_key_expired.return_value = True
            mock_get.return_value = mock_service

            result = _maybe_pgp_encrypt(
                html_body="<p>Hello</p>",
                pgp_fingerprint="EXPIRED_FP",
            )
            assert result is None

    def test_returns_none_on_encryption_error(self):
        """``_maybe_pgp_encrypt`` must return None on encryption error (fail-open)."""
        from app.core.smtp import _maybe_pgp_encrypt

        with patch("app.services.pgp_service.get_pgp_service") as mock_get:
            mock_service = MagicMock()
            mock_service.is_key_expired.return_value = False
            mock_service.encrypt_message.side_effect = Exception("GPG error")
            mock_get.return_value = mock_service

            result = _maybe_pgp_encrypt(
                html_body="<p>Hello</p>",
                pgp_fingerprint="VALID_FP",
            )
            assert result is None

    def test_returns_encrypted_body_on_success(self):
        """``_maybe_pgp_encrypt`` must return encrypted body on success."""
        from app.core.smtp import _maybe_pgp_encrypt

        with patch("app.services.pgp_service.get_pgp_service") as mock_get:
            mock_service = MagicMock()
            mock_service.is_key_expired.return_value = False
            mock_service.encrypt_message.return_value = (
                "-----BEGIN PGP MESSAGE-----\nencrypted\n"
                "-----END PGP MESSAGE-----"
            )
            mock_get.return_value = mock_service

            result = _maybe_pgp_encrypt(
                html_body="<p>Hello</p>",
                pgp_fingerprint="VALID_FP",
            )
            assert result is not None
            assert "BEGIN PGP MESSAGE" in result
