"""Hinweisgebersystem – Encryption Module.

Provides:
- **AES-256-GCM file encryption** with 12-byte nonce prepended to ciphertext.
  Used for encrypting file attachments *before* uploading to MinIO.
- **Envelope encryption helpers** for per-tenant Data Encryption Keys (DEKs).
  Each tenant has its own DEK encrypted with the application master key.
- **SHA-256 integrity verification** for uploaded files.
- **PGPString TypeDecorator** for transparent field-level encryption via
  PostgreSQL's ``pgcrypto`` extension.

Usage::

    from app.core.encryption import (
        encrypt_file,
        decrypt_file,
        generate_file_key,
        compute_sha256,
        verify_sha256,
        encrypt_dek,
        decrypt_dek,
        PGPString,
    )

    # File encryption
    key = generate_file_key()
    encrypted_data = encrypt_file(data, key)
    original_data = decrypt_file(encrypted_data, key)

    # Integrity check
    digest = compute_sha256(data)
    verify_sha256(data, digest)  # raises ValueError on mismatch

    # Envelope encryption (tenant DEK ↔ master key)
    encrypted_dek = encrypt_dek(raw_dek, master_key_hex)
    raw_dek = decrypt_dek(encrypted_dek, master_key_hex)
"""

from __future__ import annotations

import hashlib
import os

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, TypeDecorator, func, type_coerce
from sqlalchemy.dialects.postgresql import BYTEA

logger = structlog.get_logger(__name__)

# AES-256 requires a 32-byte key.
_AES_KEY_BYTES = 32

# GCM nonce length – 12 bytes is the recommended size for AES-GCM.
_NONCE_BYTES = 12


# ── AES-256-GCM File Encryption ─────────────────────────────


def generate_file_key() -> bytes:
    """Generate a cryptographically random 256-bit key for file encryption.

    Returns
    -------
    bytes
        A 32-byte random key suitable for AES-256-GCM.
    """
    return os.urandom(_AES_KEY_BYTES)


def encrypt_file(data: bytes, key: bytes) -> bytes:
    """Encrypt file data using AES-256-GCM.

    The 12-byte nonce is prepended to the ciphertext so that a single
    ``bytes`` blob can be stored (and later decrypted) without keeping
    the nonce separately.

    Parameters
    ----------
    data:
        Plaintext file contents.
    key:
        32-byte AES-256 key (use :func:`generate_file_key`).

    Returns
    -------
    bytes
        ``nonce (12 bytes) || ciphertext+tag``.

    Raises
    ------
    ValueError
        If the key length is not 32 bytes.
    """
    if len(key) != _AES_KEY_BYTES:
        raise ValueError(
            f"AES-256 key must be {_AES_KEY_BYTES} bytes, got {len(key)}."
        )

    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_file(encrypted_data: bytes, key: bytes) -> bytes:
    """Decrypt file data previously encrypted with :func:`encrypt_file`.

    Expects the first 12 bytes of *encrypted_data* to be the nonce,
    followed by the AES-GCM ciphertext + authentication tag.

    Parameters
    ----------
    encrypted_data:
        ``nonce (12 bytes) || ciphertext+tag`` as returned by
        :func:`encrypt_file`.
    key:
        The same 32-byte AES-256 key used during encryption.

    Returns
    -------
    bytes
        Decrypted plaintext.

    Raises
    ------
    ValueError
        If the key length is incorrect or the data is too short to
        contain a valid nonce + ciphertext.
    cryptography.exceptions.InvalidTag
        If the ciphertext was tampered with or the wrong key is used.
    """
    if len(key) != _AES_KEY_BYTES:
        raise ValueError(
            f"AES-256 key must be {_AES_KEY_BYTES} bytes, got {len(key)}."
        )

    if len(encrypted_data) <= _NONCE_BYTES:
        raise ValueError(
            "Encrypted data is too short to contain a nonce and ciphertext."
        )

    nonce = encrypted_data[:_NONCE_BYTES]
    ciphertext = encrypted_data[_NONCE_BYTES:]

    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ── SHA-256 Integrity Verification ──────────────────────────


def compute_sha256(data: bytes) -> str:
    """Compute the SHA-256 hex digest of *data*.

    Parameters
    ----------
    data:
        Arbitrary bytes (typically file contents before encryption).

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest (64 characters).
    """
    return hashlib.sha256(data).hexdigest()


def verify_sha256(data: bytes, expected_digest: str) -> None:
    """Verify that *data* matches the *expected_digest*.

    Parameters
    ----------
    data:
        Bytes to verify.
    expected_digest:
        Expected hex-encoded SHA-256 digest.

    Raises
    ------
    ValueError
        If the computed digest does not match *expected_digest*.
    """
    actual = compute_sha256(data)
    if actual != expected_digest.lower():
        raise ValueError(
            f"SHA-256 integrity check failed: "
            f"expected {expected_digest!r}, got {actual!r}."
        )


# ── Envelope Encryption (Master Key ↔ Tenant DEK) ──────────


def _master_key_from_hex(master_key_hex: str) -> bytes:
    """Decode a hex-encoded master key and validate its length.

    Parameters
    ----------
    master_key_hex:
        64-character hex string representing a 256-bit key.

    Returns
    -------
    bytes
        32-byte key.

    Raises
    ------
    ValueError
        If the hex string is malformed or decodes to the wrong length.
    """
    try:
        key_bytes = bytes.fromhex(master_key_hex)
    except ValueError as exc:
        raise ValueError(
            "Master key must be a valid hex-encoded string."
        ) from exc

    if len(key_bytes) != _AES_KEY_BYTES:
        raise ValueError(
            f"Master key must decode to {_AES_KEY_BYTES} bytes "
            f"({_AES_KEY_BYTES * 2} hex characters), "
            f"got {len(key_bytes)} bytes."
        )
    return key_bytes


def encrypt_dek(raw_dek: bytes, master_key_hex: str) -> bytes:
    """Encrypt a raw Data Encryption Key (DEK) with the master key.

    Uses AES-256-GCM with a random 12-byte nonce prepended to the
    result – the same format as file encryption.

    Parameters
    ----------
    raw_dek:
        The plaintext DEK bytes (typically 32 bytes for AES-256).
    master_key_hex:
        Hex-encoded 256-bit master key from environment configuration.

    Returns
    -------
    bytes
        ``nonce (12 bytes) || ciphertext+tag`` of the encrypted DEK.
    """
    master_key = _master_key_from_hex(master_key_hex)
    return encrypt_file(raw_dek, master_key)


def decrypt_dek(encrypted_dek: bytes, master_key_hex: str) -> bytes:
    """Decrypt an encrypted DEK using the master key.

    Parameters
    ----------
    encrypted_dek:
        ``nonce || ciphertext+tag`` as produced by :func:`encrypt_dek`.
    master_key_hex:
        Hex-encoded 256-bit master key from environment configuration.

    Returns
    -------
    bytes
        The raw DEK bytes.

    Raises
    ------
    ValueError
        If the master key is invalid or the data is too short.
    cryptography.exceptions.InvalidTag
        If the encrypted DEK was tampered with or the wrong master key
        is used.
    """
    master_key = _master_key_from_hex(master_key_hex)
    return decrypt_file(encrypted_dek, master_key)


def generate_tenant_dek() -> bytes:
    """Generate a new random 256-bit DEK for a tenant.

    Returns
    -------
    bytes
        A 32-byte random key.
    """
    return os.urandom(_AES_KEY_BYTES)


# ── PGPString – Transparent pgcrypto Column Encryption ──────


class PGPString(TypeDecorator):
    """SQLAlchemy TypeDecorator for transparent field-level encryption
    using PostgreSQL's ``pgcrypto`` extension (``pgp_sym_encrypt`` /
    ``pgp_sym_decrypt``).

    The *passphrase* is a per-tenant DEK that is decrypted from
    envelope encryption at runtime.  The column is stored as ``BYTEA``
    in PostgreSQL.

    Usage in a model::

        from app.core.encryption import PGPString

        class Report(Base):
            __tablename__ = "reports"
            subject = Column(PGPString("tenant-dek-passphrase"))

    .. note::

        ``cache_ok = True`` is required by SQLAlchemy for custom
        TypeDecorators that participate in query caching.  The
        passphrase is a per-instance parameter that does not affect
        the SQL structure.
    """

    impl = BYTEA
    cache_ok = True

    def __init__(self, passphrase: str) -> None:
        super().__init__()
        self.passphrase = passphrase

    def bind_expression(self, bindvalue):
        """Encrypt on INSERT/UPDATE — wraps the bound value with
        ``pgp_sym_encrypt(value, passphrase)``."""
        bindvalue = type_coerce(bindvalue, String)
        return func.pgp_sym_encrypt(bindvalue, self.passphrase)

    def column_expression(self, col):
        """Decrypt on SELECT — wraps the column with
        ``pgp_sym_decrypt(col, passphrase)``."""
        return func.pgp_sym_decrypt(col, self.passphrase)
