"""Hinweisgebersystem -- Encryption Module Tests.

Tests:
- AES-256-GCM file encryption / decryption round-trip.
- Nonce uniqueness across multiple encryptions.
- Wrong-key decryption failure (``InvalidTag``).
- Invalid key lengths.
- Data-too-short edge case for decryption.
- SHA-256 integrity computation and verification.
- SHA-256 verification failure on tampered data.
- Envelope encryption (DEK encrypt/decrypt via master key).
- PGPString TypeDecorator SQL expression generation.
"""

from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import String, func, type_coerce

from app.core.encryption import (
    PGPString,
    _AES_KEY_BYTES,
    _NONCE_BYTES,
    compute_sha256,
    decrypt_dek,
    decrypt_file,
    encrypt_dek,
    encrypt_file,
    generate_file_key,
    generate_tenant_dek,
    verify_sha256,
)


# ── AES-256-GCM File Encryption ─────────────────────────────


class TestGenerateFileKey:
    """Tests for ``generate_file_key``."""

    def test_key_length(self):
        """Generated key must be exactly 32 bytes (256 bits)."""
        key = generate_file_key()
        assert isinstance(key, bytes)
        assert len(key) == _AES_KEY_BYTES

    def test_key_randomness(self):
        """Successive calls must produce different keys."""
        keys = {generate_file_key() for _ in range(50)}
        assert len(keys) == 50


class TestEncryptDecryptFile:
    """Tests for ``encrypt_file`` / ``decrypt_file`` round-trip."""

    def test_round_trip_basic(self):
        """Encrypt then decrypt must return the original plaintext."""
        key = generate_file_key()
        plaintext = b"Whistleblower report content: confidential."

        encrypted = encrypt_file(plaintext, key)
        decrypted = decrypt_file(encrypted, key)

        assert decrypted == plaintext

    def test_round_trip_empty_data(self):
        """Encrypting and decrypting empty bytes must work correctly."""
        key = generate_file_key()
        plaintext = b""

        encrypted = encrypt_file(plaintext, key)
        decrypted = decrypt_file(encrypted, key)

        assert decrypted == plaintext

    def test_round_trip_large_data(self):
        """Round-trip must work for large payloads (1 MB)."""
        key = generate_file_key()
        plaintext = os.urandom(1024 * 1024)  # 1 MB random data

        encrypted = encrypt_file(plaintext, key)
        decrypted = decrypt_file(encrypted, key)

        assert decrypted == plaintext

    def test_encrypted_output_contains_nonce(self):
        """Encrypted output must be longer than plaintext by at least
        nonce (12 bytes) + GCM tag (16 bytes)."""
        key = generate_file_key()
        plaintext = b"test data"

        encrypted = encrypt_file(plaintext, key)

        # nonce (12) + plaintext (9) + GCM tag (16) = 37
        assert len(encrypted) > len(plaintext) + _NONCE_BYTES

    def test_nonce_uniqueness(self):
        """Each encryption must use a unique nonce (first 12 bytes)."""
        key = generate_file_key()
        plaintext = b"same input"

        nonces = set()
        for _ in range(100):
            encrypted = encrypt_file(plaintext, key)
            nonce = encrypted[:_NONCE_BYTES]
            nonces.add(nonce)

        assert len(nonces) == 100

    def test_different_ciphertext_same_input(self):
        """Same plaintext + same key must produce different ciphertext
        due to random nonce (semantic security)."""
        key = generate_file_key()
        plaintext = b"identical input"

        ct1 = encrypt_file(plaintext, key)
        ct2 = encrypt_file(plaintext, key)

        assert ct1 != ct2

    def test_wrong_key_raises_invalid_tag(self):
        """Decrypting with a different key must raise ``InvalidTag``."""
        key1 = generate_file_key()
        key2 = generate_file_key()
        plaintext = b"secret data"

        encrypted = encrypt_file(plaintext, key1)

        with pytest.raises(InvalidTag):
            decrypt_file(encrypted, key2)

    def test_tampered_ciphertext_raises_invalid_tag(self):
        """Flipping a byte in the ciphertext must raise ``InvalidTag``."""
        key = generate_file_key()
        encrypted = encrypt_file(b"important data", key)

        # Tamper with a byte in the ciphertext (after the nonce)
        tampered = bytearray(encrypted)
        tampered[_NONCE_BYTES + 1] ^= 0xFF
        tampered = bytes(tampered)

        with pytest.raises(InvalidTag):
            decrypt_file(tampered, key)

    def test_invalid_key_length_encrypt(self):
        """Encryption must reject keys that are not 32 bytes."""
        short_key = os.urandom(16)
        with pytest.raises(ValueError, match="AES-256 key must be"):
            encrypt_file(b"data", short_key)

    def test_invalid_key_length_decrypt(self):
        """Decryption must reject keys that are not 32 bytes."""
        long_key = os.urandom(48)
        fake_encrypted = os.urandom(64)
        with pytest.raises(ValueError, match="AES-256 key must be"):
            decrypt_file(fake_encrypted, long_key)

    def test_data_too_short_for_decryption(self):
        """Decryption must reject data shorter than the nonce."""
        key = generate_file_key()
        too_short = os.urandom(_NONCE_BYTES)  # exactly nonce length, no ciphertext

        with pytest.raises(ValueError, match="too short"):
            decrypt_file(too_short, key)


# ── SHA-256 Integrity Verification ──────────────────────────


class TestSHA256:
    """Tests for ``compute_sha256`` and ``verify_sha256``."""

    def test_compute_sha256_known_value(self):
        """Verify against a known SHA-256 digest."""
        # SHA-256 of empty bytes is a well-known constant.
        expected = (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )
        assert compute_sha256(b"") == expected

    def test_compute_sha256_deterministic(self):
        """Same input must always produce the same digest."""
        data = b"deterministic test input"
        assert compute_sha256(data) == compute_sha256(data)

    def test_compute_sha256_different_input(self):
        """Different inputs must produce different digests."""
        assert compute_sha256(b"alice") != compute_sha256(b"bob")

    def test_compute_sha256_format(self):
        """Digest must be a 64-character lowercase hex string."""
        digest = compute_sha256(b"format test")
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(c in "0123456789abcdef" for c in digest)

    def test_verify_sha256_valid(self):
        """``verify_sha256`` must not raise for matching data."""
        data = b"file contents"
        digest = compute_sha256(data)
        verify_sha256(data, digest)  # Should not raise

    def test_verify_sha256_case_insensitive(self):
        """``verify_sha256`` must accept uppercase digest strings."""
        data = b"case insensitive test"
        digest = compute_sha256(data).upper()
        verify_sha256(data, digest)  # Should not raise

    def test_verify_sha256_mismatch(self):
        """``verify_sha256`` must raise ``ValueError`` on mismatch."""
        data = b"original"
        wrong_digest = compute_sha256(b"tampered")

        with pytest.raises(ValueError, match="SHA-256 integrity check failed"):
            verify_sha256(data, wrong_digest)

    def test_verify_sha256_corrupt_digest(self):
        """Completely invalid digest must trigger a mismatch error."""
        data = b"test"
        with pytest.raises(ValueError, match="SHA-256 integrity check failed"):
            verify_sha256(data, "0" * 64)


# ── Envelope Encryption (Master Key ↔ Tenant DEK) ──────────


class TestEnvelopeEncryption:
    """Tests for ``encrypt_dek`` / ``decrypt_dek`` and ``generate_tenant_dek``."""

    def test_generate_tenant_dek_length(self):
        """Tenant DEK must be 32 bytes (256 bits)."""
        dek = generate_tenant_dek()
        assert len(dek) == _AES_KEY_BYTES

    def test_dek_round_trip(self):
        """Encrypting and decrypting a DEK must return the original bytes."""
        master_key_hex = os.urandom(_AES_KEY_BYTES).hex()
        raw_dek = generate_tenant_dek()

        encrypted = encrypt_dek(raw_dek, master_key_hex)
        decrypted = decrypt_dek(encrypted, master_key_hex)

        assert decrypted == raw_dek

    def test_dek_wrong_master_key(self):
        """Decrypting with a different master key must fail."""
        mk1 = os.urandom(_AES_KEY_BYTES).hex()
        mk2 = os.urandom(_AES_KEY_BYTES).hex()
        raw_dek = generate_tenant_dek()

        encrypted = encrypt_dek(raw_dek, mk1)

        with pytest.raises(InvalidTag):
            decrypt_dek(encrypted, mk2)

    def test_invalid_master_key_hex(self):
        """Non-hex master key string must raise ``ValueError``."""
        with pytest.raises(ValueError, match="valid hex"):
            encrypt_dek(b"dek", "not-hex-at-all!!!")

    def test_master_key_wrong_length(self):
        """Master key that decodes to wrong byte length must raise."""
        short_hex = os.urandom(16).hex()  # Only 16 bytes (32 hex chars)
        with pytest.raises(ValueError, match="32 bytes"):
            encrypt_dek(b"dek", short_hex)


# ── PGPString TypeDecorator ──────────────────────────────────


class TestPGPString:
    """Tests for ``PGPString`` SQLAlchemy TypeDecorator.

    These are unit tests for the SQL expression generation, NOT
    integration tests requiring a live PostgreSQL with pgcrypto.
    """

    def test_cache_ok(self):
        """``cache_ok`` must be ``True`` for query-cache compatibility."""
        assert PGPString.cache_ok is True

    def test_impl_is_bytea(self):
        """The underlying column type must be ``BYTEA``."""
        from sqlalchemy.dialects.postgresql import BYTEA

        pgp = PGPString("test-passphrase")
        assert isinstance(pgp.impl, BYTEA)

    def test_bind_expression_produces_pgp_sym_encrypt(self):
        """``bind_expression`` must wrap the value with
        ``pgp_sym_encrypt(...)``."""
        pgp = PGPString("my-secret-key")

        from sqlalchemy import column

        col = column("subject", String)
        expr = pgp.bind_expression(col)

        # The compiled SQL should reference pgp_sym_encrypt
        compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
        assert "pgp_sym_encrypt" in compiled

    def test_column_expression_produces_pgp_sym_decrypt(self):
        """``column_expression`` must wrap the column with
        ``pgp_sym_decrypt(...)``."""
        pgp = PGPString("my-secret-key")

        from sqlalchemy import column
        from sqlalchemy.dialects.postgresql import BYTEA

        col = column("subject", BYTEA)
        expr = pgp.column_expression(col)

        compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
        assert "pgp_sym_decrypt" in compiled

    def test_passphrase_stored(self):
        """The passphrase must be accessible on the instance."""
        passphrase = "tenant-dek-12345"
        pgp = PGPString(passphrase)
        assert pgp.passphrase == passphrase
