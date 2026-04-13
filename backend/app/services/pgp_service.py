"""Hinweisgebersystem – PGP Email Encryption Service.

Provides PGP key management and email body encryption using
``python-gnupg`` with the following features:

- **Key import & validation**: Import ASCII-armored public keys,
  extract fingerprint and expiry date, reject private keys.
- **Key expiry checking**: Determine whether a stored key has expired.
- **Email body encryption**: Encrypt plaintext (HTML or plain) for a
  recipient using their imported PGP public key.
- **Key deletion**: Remove a key from the GPG keyring.

The service uses a per-instance GPG keyring directory (configured via
``PGP_KEYRING_PATH`` environment variable or default path).

Usage::

    from app.services.pgp_service import PGPService

    pgp = PGPService()

    # Import a public key:
    fingerprint, expires_at = pgp.import_key(armored_key_text)

    # Encrypt an email body:
    encrypted_body = pgp.encrypt_message("Hello, world!", fingerprint)

    # Check if a key is expired:
    is_expired = pgp.is_key_expired(fingerprint)

    # Delete a key:
    pgp.delete_key(fingerprint)
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass

import gnupg
import structlog

logger = structlog.get_logger(__name__)

# Default keyring path when PGP_KEYRING_PATH env var is not set.
_DEFAULT_KEYRING_PATH = os.path.join(tempfile.gettempdir(), ".gnupg-hinweisgebersystem")


# ── Exceptions ───────────────────────────────────────────────


class PGPError(Exception):
    """Base exception for all PGP service errors."""


class PGPKeyImportError(PGPError):
    """Raised when a PGP key cannot be imported or is invalid."""


class PGPKeyExpiredError(PGPError):
    """Raised when a PGP key has expired."""


class PGPEncryptionError(PGPError):
    """Raised when PGP encryption fails."""


# ── Key metadata ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PGPKeyInfo:
    """Immutable metadata extracted from an imported PGP public key.

    Attributes
    ----------
    fingerprint : str
        Full 40-character hex fingerprint of the key.
    expires_at : datetime | None
        Expiration timestamp (``None`` if the key does not expire).
    user_ids : list[str]
        List of user ID strings (name + email) associated with the key.
    """

    fingerprint: str
    expires_at: datetime | None
    user_ids: list[str]


# ── PGP Service ──────────────────────────────────────────────


class PGPService:
    """PGP key management and email encryption service.

    Uses ``python-gnupg`` to manage a GPG keyring for importing
    public keys and encrypting email bodies before sending.

    Parameters
    ----------
    keyring_path : str | None
        Path to the GPG keyring directory.  If ``None``, reads from
        the ``PGP_KEYRING_PATH`` environment variable or falls back
        to a default temporary directory.
    """

    def __init__(self, keyring_path: str | None = None) -> None:
        self._keyring_path = (
            keyring_path
            or os.environ.get("PGP_KEYRING_PATH")
            or _DEFAULT_KEYRING_PATH
        )
        # Ensure the keyring directory exists with restricted permissions.
        os.makedirs(self._keyring_path, mode=0o700, exist_ok=True)

        self._gpg = gnupg.GPG(gnupghome=self._keyring_path)
        # Disable interactive passphrase prompts.
        self._gpg.encoding = "utf-8"

        logger.info(
            "pgp_service_initialised",
            keyring_path=self._keyring_path,
        )

    # ── Key Import ───────────────────────────────────────────

    def import_key(self, armored_key: str) -> PGPKeyInfo:
        """Import an ASCII-armored PGP public key into the keyring.

        Parameters
        ----------
        armored_key : str
            The ASCII-armored PGP public key text (``-----BEGIN PGP
            PUBLIC KEY BLOCK-----`` … ``-----END PGP PUBLIC KEY
            BLOCK-----``).

        Returns
        -------
        PGPKeyInfo
            Extracted key metadata (fingerprint, expiry, user IDs).

        Raises
        ------
        PGPKeyImportError
            If the key is invalid, is a private key, or the import
            fails for any other reason.
        """
        # Reject private keys.
        if "PRIVATE KEY" in armored_key.upper():
            raise PGPKeyImportError(
                "Private keys must not be uploaded. "
                "Please provide a public key only."
            )

        # Validate that it looks like an armored PGP block.
        if "BEGIN PGP PUBLIC KEY BLOCK" not in armored_key:
            raise PGPKeyImportError(
                "Invalid key format. Expected an ASCII-armored PGP "
                "public key (-----BEGIN PGP PUBLIC KEY BLOCK-----)."
            )

        result = self._gpg.import_keys(armored_key)

        if not result.fingerprints:
            raise PGPKeyImportError(
                "Failed to import PGP key. The key data may be "
                f"corrupt or unsupported. GPG result: {result.results}"
            )

        fingerprint = result.fingerprints[0]

        # Extract key details from the keyring.
        key_info = self._get_key_info(fingerprint)

        # Check if the key is already expired.
        if key_info.expires_at and key_info.expires_at < datetime.now(timezone.utc):
            # Delete the expired key from the keyring.
            self._gpg.delete_keys(fingerprint)
            raise PGPKeyImportError(
                "The PGP key has already expired and cannot be used."
            )

        logger.info(
            "pgp_key_imported",
            fingerprint=fingerprint,
            expires_at=str(key_info.expires_at) if key_info.expires_at else "never",
            user_ids=key_info.user_ids,
        )

        return key_info

    # ── Key Info ─────────────────────────────────────────────

    def _get_key_info(self, fingerprint: str) -> PGPKeyInfo:
        """Extract metadata for a key in the keyring by fingerprint.

        Parameters
        ----------
        fingerprint : str
            The 40-character hex fingerprint of the key.

        Returns
        -------
        PGPKeyInfo
            Key metadata.

        Raises
        ------
        PGPKeyImportError
            If the key is not found in the keyring.
        """
        keys = self._gpg.list_keys()

        for key in keys:
            if key["fingerprint"] == fingerprint:
                # Parse expiry timestamp.
                expires_at: datetime | None = None
                if key.get("expires") and key["expires"]:
                    try:
                        expires_at = datetime.fromtimestamp(
                            int(key["expires"]),
                            tz=timezone.utc,
                        )
                    except (ValueError, OSError):
                        expires_at = None

                # Extract user IDs.
                user_ids = key.get("uids", [])

                return PGPKeyInfo(
                    fingerprint=fingerprint,
                    expires_at=expires_at,
                    user_ids=list(user_ids),
                )

        raise PGPKeyImportError(
            f"Key with fingerprint {fingerprint} not found in keyring."
        )

    # ── Key Expiry Check ─────────────────────────────────────

    def is_key_expired(self, fingerprint: str) -> bool:
        """Check whether a key in the keyring has expired.

        Parameters
        ----------
        fingerprint : str
            The 40-character hex fingerprint of the key.

        Returns
        -------
        bool
            ``True`` if the key has expired or cannot be found,
            ``False`` if the key is still valid.
        """
        try:
            key_info = self._get_key_info(fingerprint)
        except PGPKeyImportError:
            logger.warning(
                "pgp_key_not_found_for_expiry_check",
                fingerprint=fingerprint,
            )
            return True

        if key_info.expires_at is None:
            return False

        expired = key_info.expires_at < datetime.now(timezone.utc)

        if expired:
            logger.warning(
                "pgp_key_expired",
                fingerprint=fingerprint,
                expired_at=str(key_info.expires_at),
            )

        return expired

    # ── Message Encryption ───────────────────────────────────

    def encrypt_message(
        self,
        plaintext: str,
        fingerprint: str,
        *,
        always_trust: bool = True,
    ) -> str:
        """Encrypt a plaintext message for a recipient's PGP key.

        Parameters
        ----------
        plaintext : str
            The message body to encrypt (HTML or plain text).
        fingerprint : str
            The recipient's PGP key fingerprint.
        always_trust : bool
            Whether to skip trust-level validation.  Defaults to
            ``True`` because server-managed keys are always imported
            by administrators.

        Returns
        -------
        str
            The ASCII-armored PGP-encrypted message.

        Raises
        ------
        PGPKeyExpiredError
            If the recipient's key has expired.
        PGPEncryptionError
            If encryption fails for any other reason.
        """
        # Verify the key is not expired before encrypting.
        if self.is_key_expired(fingerprint):
            raise PGPKeyExpiredError(
                f"Cannot encrypt: PGP key {fingerprint} has expired."
            )

        encrypted = self._gpg.encrypt(
            plaintext,
            fingerprint,
            always_trust=always_trust,
            armor=True,
        )

        if not encrypted.ok:
            logger.error(
                "pgp_encryption_failed",
                fingerprint=fingerprint,
                status=encrypted.status,
                stderr=encrypted.stderr,
            )
            raise PGPEncryptionError(
                f"PGP encryption failed: {encrypted.status}"
            )

        logger.debug(
            "pgp_message_encrypted",
            fingerprint=fingerprint,
            plaintext_length=len(plaintext),
            encrypted_length=len(str(encrypted)),
        )

        return str(encrypted)

    # ── Key Deletion ─────────────────────────────────────────

    def delete_key(self, fingerprint: str) -> bool:
        """Delete a public key from the GPG keyring.

        Parameters
        ----------
        fingerprint : str
            The 40-character hex fingerprint of the key to delete.

        Returns
        -------
        bool
            ``True`` if the key was successfully deleted.

        Raises
        ------
        PGPError
            If the deletion fails.
        """
        result = self._gpg.delete_keys(fingerprint)

        if str(result) != "ok":
            raise PGPError(f"Failed to delete PGP key {fingerprint}: {result}")

        logger.info(
            "pgp_key_deleted",
            fingerprint=fingerprint,
        )

        return True


# ── Module-level singleton ───────────────────────────────────

_pgp_service: PGPService | None = None


def get_pgp_service() -> PGPService:
    """Return a lazily-initialised PGP service singleton.

    The singleton is created on first call and reused for all
    subsequent calls within the same process.

    Returns
    -------
    PGPService
        The global PGP service instance.
    """
    global _pgp_service  # noqa: PLW0603

    if _pgp_service is None:
        _pgp_service = PGPService()

    return _pgp_service
