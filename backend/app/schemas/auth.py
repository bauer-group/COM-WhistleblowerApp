"""Hinweisgebersystem – Authentication Pydantic Schemas.

Request and response schemas for:
- Anonymous mailbox login (case number + passphrase/password)
- Magic link request and verification (non-anonymous reporters)
- OIDC callback processing (admin users)
- TOTP 2FA challenge during OIDC login

These schemas handle the reporter-facing authentication flows.
Admin OIDC authentication is handled separately by the security
module, but the token response schema is shared.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.report import Channel, ReportStatus


# ── Mailbox Login (Case Number + Passphrase/Password) ────────


class MailboxLoginRequest(BaseModel):
    """Schema for anonymous mailbox login.

    The reporter authenticates with their 16-character case number
    and either the system-generated 6-word passphrase or their
    self-chosen password.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    case_number: str = Field(
        min_length=16,
        max_length=16,
        description="16-character case number received at report submission.",
    )
    passphrase: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "6-word passphrase (space-separated) or self-chosen password."
        ),
    )


class MailboxLoginResponse(BaseModel):
    """Response after successful mailbox login.

    Returns a session token and basic case information for the
    mailbox UI.  The session is cookie-based (httpOnly) and expires
    on browser close (anonymous mode) or after 24h (magic link).
    """

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(
        description="JWT session token for the mailbox API.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer').",
    )
    expires_at: datetime = Field(
        description="Token expiration timestamp (UTC).",
    )
    case_number: str = Field(
        description="Confirmed case number.",
    )
    channel: Channel = Field(
        description="Reporting channel (HinSchG or LkSG).",
    )
    status: ReportStatus = Field(
        description="Current case status.",
    )


# ── Magic Link Request ────────────────────────────────────────


class MagicLinkRequest(BaseModel):
    """Schema for requesting a magic link email.

    Non-anonymous reporters can request a passwordless login link
    sent to their registered email address.  Rate-limited to 3
    requests per email per hour.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    case_number: str = Field(
        min_length=16,
        max_length=16,
        description="16-character case number.",
    )
    email: EmailStr = Field(
        description="Email address registered with the report.",
    )


class MagicLinkResponse(BaseModel):
    """Response after magic link request.

    Always returns a success message regardless of whether the email
    was found, to prevent user enumeration attacks.
    """

    model_config = ConfigDict(frozen=True)

    message: str = Field(
        default="If the email matches a report, a login link has been sent.",
        description="Human-readable confirmation message.",
    )


# ── Magic Link Verification ──────────────────────────────────


class MagicLinkVerify(BaseModel):
    """Schema for verifying a magic link token.

    The token is a JWT signed with the application's secret key,
    containing the case number and email.  Expires after 15 minutes.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(
        min_length=1,
        description="Magic link JWT token from the email URL.",
    )


class MagicLinkVerifyResponse(BaseModel):
    """Response after successful magic link verification.

    Returns the same session data as a mailbox login.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(
        description="JWT session token for the mailbox API.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer').",
    )
    expires_at: datetime = Field(
        description="Token expiration timestamp (UTC, 24h from now).",
    )
    case_number: str = Field(
        description="Confirmed case number.",
    )
    channel: Channel = Field(
        description="Reporting channel.",
    )
    status: ReportStatus = Field(
        description="Current case status.",
    )


# ── OIDC Callback ─────────────────────────────────────────────


class OIDCCallbackRequest(BaseModel):
    """Schema for processing the OIDC authorization code callback.

    After the user authenticates with Microsoft Entra ID, the
    frontend sends the authorization code for token exchange.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        min_length=1,
        description="Authorization code from the OIDC provider.",
    )
    state: str | None = Field(
        default=None,
        description="CSRF state parameter for validation.",
    )
    redirect_uri: str = Field(
        description="The redirect URI used in the authorization request.",
    )


class OIDCTokenResponse(BaseModel):
    """Response after successful OIDC authentication.

    Returns a session token for the admin API along with the
    authenticated user's basic information.
    """

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(
        description="JWT session token for the admin API.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer').",
    )
    expires_at: datetime = Field(
        description="Token expiration timestamp (UTC).",
    )
    user_id: UUID = Field(
        description="Authenticated user's UUID.",
    )
    email: str = Field(
        description="Authenticated user's email.",
    )
    display_name: str = Field(
        description="Authenticated user's display name.",
    )
    role: str = Field(
        description="User's RBAC role.",
    )


# ── OIDC 2FA Challenge ───────────────────────────────────────


class OIDCTwoFactorChallengeResponse(BaseModel):
    """Response when OIDC login requires a TOTP 2FA challenge.

    Returned instead of ``OIDCTokenResponse`` when the authenticated
    user has ``totp_enabled=True``.  Contains a short-lived challenge
    token (5-min expiry) that must be submitted along with a valid
    TOTP code to ``POST /auth/totp/challenge`` to obtain the full
    session token.
    """

    model_config = ConfigDict(frozen=True)

    requires_2fa: bool = Field(
        default=True,
        description="Always ``True`` — signals the frontend to show the TOTP entry form.",
    )
    challenge_token: str = Field(
        description=(
            "Short-lived JWT (5-min expiry) encoding the user identity. "
            "Submit this together with a valid TOTP code to complete login."
        ),
    )
    expires_at: datetime = Field(
        description="Challenge token expiration timestamp (UTC).",
    )


class TwoFactorCheckResponse(BaseModel):
    """Response for the 2FA status check endpoint.

    Returned by ``POST /auth/2fa-check`` after the frontend completes
    OIDC authentication.  If the user has TOTP enabled, ``requires_2fa``
    is ``True`` and a short-lived ``challenge_token`` is included.
    """

    model_config = ConfigDict(frozen=True)

    requires_2fa: bool = Field(
        description="Whether the user must complete a TOTP challenge before proceeding.",
    )
    challenge_token: str | None = Field(
        default=None,
        description=(
            "Short-lived JWT (5-min expiry) for TOTP verification.  "
            "Present only when ``requires_2fa`` is ``True``."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Challenge token expiration timestamp (UTC).  Null when 2FA is not required.",
    )


class TOTPChallengeRequest(BaseModel):
    """Request to complete a TOTP 2FA challenge during OIDC login.

    After receiving an ``OIDCTwoFactorChallengeResponse``, the frontend
    collects a 6-digit TOTP code and submits it together with the
    challenge token to ``POST /auth/totp/challenge``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    challenge_token: str = Field(
        min_length=1,
        description="Challenge token received from the OIDC callback.",
    )
    code: str = Field(
        min_length=6,
        max_length=8,
        pattern=r"^[A-Z0-9]{6,8}$",
        description="6-digit TOTP code or 8-character backup code.",
    )


# ── Token Refresh ─────────────────────────────────────────────


class TokenRefreshResponse(BaseModel):
    """Response after refreshing a session token."""

    model_config = ConfigDict(frozen=True)

    access_token: str = Field(
        description="New JWT session token.",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer').",
    )
    expires_at: datetime = Field(
        description="New token expiration timestamp (UTC).",
    )
