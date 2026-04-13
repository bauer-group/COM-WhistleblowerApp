"""Hinweisgebersystem – PGP Key Management Pydantic Schemas.

Request and response schemas for PGP public key upload and management
on backend user accounts.  These schemas are used by the
``/admin/users/{user_id}/pgp-key`` endpoints.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── PGP Key Upload ─────────────────────────────────────────────


class PGPKeyUpload(BaseModel):
    """Schema for uploading an ASCII-armored PGP public key.

    The key is validated, imported into the GPG keyring, and its
    fingerprint and expiry are extracted.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    public_key: str = Field(
        min_length=100,
        max_length=65536,
        description=(
            "ASCII-armored PGP public key "
            "(-----BEGIN PGP PUBLIC KEY BLOCK----- … "
            "-----END PGP PUBLIC KEY BLOCK-----)."
        ),
    )


# ── PGP Key Response ──────────────────────────────────────────


class PGPKeyResponse(BaseModel):
    """Response after successfully uploading a PGP public key."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str = Field(
        description="40-character hex fingerprint of the imported PGP key.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Expiration timestamp of the PGP key (null if the key "
            "does not expire)."
        ),
    )
    user_ids: list[str] = Field(
        default_factory=list,
        description="User IDs (name + email) associated with the PGP key.",
    )
    message: str = Field(
        default="PGP public key has been uploaded successfully.",
        description="Human-readable confirmation message.",
    )


# ── PGP Key Delete Response ──────────────────────────────────


class PGPKeyDeleteResponse(BaseModel):
    """Response after successfully deleting a PGP public key."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(
        default="PGP public key has been removed.",
        description="Human-readable confirmation message.",
    )
