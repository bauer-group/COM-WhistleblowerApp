"""Hinweisgebersystem – TOTP Two-Factor Authentication Pydantic Schemas.

Request and response schemas for:
- TOTP setup (generate secret + QR URI + backup codes)
- TOTP verification (activate 2FA with 6-digit code)
- TOTP disable (deactivate own 2FA)
- Admin TOTP reset (admin resets another user's 2FA)

These schemas are used by the ``/auth/totp/*`` and
``/admin/users/{user_id}/totp`` endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ── TOTP Setup ───────────────────────────────────────────────


class TOTPSetupResponse(BaseModel):
    """Response after initiating TOTP setup.

    Contains the TOTP secret, provisioning URI (for QR code
    generation), and 10 single-use backup codes.  The backup
    codes are shown in plaintext exactly once — they are stored
    as bcrypt hashes and cannot be recovered.
    """

    model_config = ConfigDict(frozen=True)

    secret: str = Field(
        description="Base32-encoded TOTP shared secret.",
    )
    provisioning_uri: str = Field(
        description=(
            "otpauth:// URI for QR code generation "
            "(includes issuer, account, secret, algorithm, digits, period)."
        ),
    )
    backup_codes: list[str] = Field(
        description=(
            "10 single-use backup/recovery codes (plaintext, shown once). "
            "Each code can be used exactly once in place of a TOTP code."
        ),
    )


# ── TOTP Verify (activate 2FA) ──────────────────────────────


class TOTPVerifyRequest(BaseModel):
    """Request to verify a TOTP code and activate 2FA.

    After scanning the QR code or entering the secret into an
    authenticator app, the user submits a 6-digit code to confirm
    correct setup.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-digit TOTP code from the authenticator app.",
    )


class TOTPVerifyResponse(BaseModel):
    """Response after successful TOTP verification.

    Confirms that 2FA has been activated on the user's account.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Whether TOTP 2FA is now enabled.",
    )
    message: str = Field(
        default="Two-factor authentication has been enabled.",
        description="Human-readable confirmation message.",
    )


# ── TOTP Disable ─────────────────────────────────────────────


class TOTPDisableRequest(BaseModel):
    """Request to disable TOTP 2FA on the current user's account.

    Requires a valid TOTP code to confirm identity before disabling.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="Current 6-digit TOTP code to confirm identity.",
    )


class TOTPDisableResponse(BaseModel):
    """Response after successfully disabling TOTP 2FA."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Whether TOTP 2FA is now enabled (always false).",
    )
    message: str = Field(
        default="Two-factor authentication has been disabled.",
        description="Human-readable confirmation message.",
    )


# ── Admin TOTP Reset ────────────────────────────────────────


class TOTPAdminResetResponse(BaseModel):
    """Response after an admin resets another user's TOTP 2FA."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(
        default="Two-factor authentication has been reset for the user.",
        description="Human-readable confirmation message.",
    )
