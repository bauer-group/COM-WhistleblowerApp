"""Hinweisgebersystem – Authentication API Endpoints.

Provides:
- **POST /auth/magic-link/request** — Request a magic link email for
  non-anonymous reporters.  Rate-limited to 3 requests per email per hour.
- **POST /auth/magic-link/verify** — Verify a magic link JWT (15-min expiry)
  and issue a 24-hour httpOnly session cookie.
- **POST /auth/oidc/callback** — OIDC Authorization Code callback for admin
  login via Microsoft Entra ID.
- **POST /auth/totp/challenge** — Complete TOTP 2FA challenge during OIDC login.
- **POST /auth/totp/setup** — Generate TOTP secret + QR URI + backup codes.
- **POST /auth/totp/verify** — Verify TOTP code to activate 2FA.
- **POST /auth/totp/disable** — Disable own 2FA with code verification.

Reporter authentication is token-based via magic links or passphrase login.
Admin authentication uses the OIDC Authorization Code Flow with PKCE —
the callback endpoint exchanges the code for tokens, validates the ID token,
and creates a session.

Usage::

    # In the v1 router aggregation:
    from app.api.v1.auth import router as auth_router
    api_v1_router.include_router(auth_router)
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from redis import asyncio as aioredis
import jwt as pyjwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, Security, status
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core.database import get_admin_session_factory, get_db, get_session_factory
from app.core.oidc import (
    build_authorization_url,
    exchange_code_for_tokens,
    validate_id_token,
)
from app.core.security import (
    create_magic_link_token,
    generate_backup_codes,
    generate_totp_provisioning_uri,
    generate_totp_secret,
    get_current_user,
    hash_backup_codes,
    verify_backup_code,
    verify_magic_link_token,
    verify_totp_code,
)
from app.schemas.auth import (
    MagicLinkRequest,
    MagicLinkResponse,
    MagicLinkVerify,
    MagicLinkVerifyResponse,
    OIDCCallbackRequest,
    OIDCTokenResponse,
    OIDCTwoFactorChallengeResponse,
    TOTPChallengeRequest,
    TwoFactorCheckResponse,
)
from app.schemas.totp import (
    TOTPDisableRequest,
    TOTPDisableResponse,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    TOTPVerifyResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── In-memory rate limiter for magic link requests ───────────
# Stores {email: [timestamp, ...]} — entries older than 1 hour are
# pruned on each check.  In production this should be backed by Redis
# for multi-process deployments; the in-memory implementation is
# sufficient for single-process dev and a placeholder for the Redis
# middleware integration (subtask-7).

_MAGIC_LINK_RATE_LIMIT = 3  # max requests per email per hour
_MAGIC_LINK_RATE_WINDOW = 3600  # 1 hour in seconds
_magic_link_requests: dict[str, list[float]] = defaultdict(list)


def _check_magic_link_rate_limit(email: str) -> bool:
    """Check whether the email has exceeded the magic link rate limit.

    Prunes stale entries and returns ``True`` if the request is allowed,
    ``False`` if the rate limit is exceeded.

    Parameters
    ----------
    email:
        Normalised (lowercased) email address.

    Returns
    -------
    bool
        ``True`` if the request may proceed.
    """
    now = time.monotonic()
    cutoff = now - _MAGIC_LINK_RATE_WINDOW

    # Prune stale timestamps.
    timestamps = _magic_link_requests[email]
    _magic_link_requests[email] = [ts for ts in timestamps if ts > cutoff]

    if len(_magic_link_requests[email]) >= _MAGIC_LINK_RATE_LIMIT:
        return False

    _magic_link_requests[email].append(now)
    return True


# ── Session JWT helpers ──────────────────────────────────────
# After successful magic-link verification or OIDC callback, we issue
# a session JWT (HS256) with a 24-hour expiry, delivered as an httpOnly
# cookie.  This keeps the session stateless on the server side.

_SESSION_COOKIE_NAME = "session_token"
_SESSION_EXPIRE_HOURS = 24


def _create_session_token(
    claims: dict,
    *,
    settings: Settings,
    expire_hours: int = _SESSION_EXPIRE_HOURS,
) -> tuple[str, datetime]:
    """Create an HS256 session JWT.

    Parameters
    ----------
    claims:
        Payload claims (``sub``, ``report_id``, ``type``, etc.).
    settings:
        Application settings (for signing key).
    expire_hours:
        Token lifetime in hours.

    Returns
    -------
    tuple[str, datetime]
        ``(encoded_token, expires_at)``
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=expire_hours)
    payload = {
        **claims,
        "iat": now,
        "exp": expires_at,
    }
    token = pyjwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def _set_session_cookie(
    response: Response,
    token: str,
    *,
    max_age: int = _SESSION_EXPIRE_HOURS * 3600,
) -> None:
    """Set the session JWT as an httpOnly cookie on the response.

    Parameters
    ----------
    response:
        FastAPI ``Response`` object.
    token:
        Encoded JWT string.
    max_age:
        Cookie max-age in seconds.
    """
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/api",
    )


# ── 2FA Challenge token helpers ──────────────────────────────
# When a user with totp_enabled=True completes OIDC login, instead
# of issuing a full session we issue a short-lived (5-min) challenge
# token.  The user must then submit a valid TOTP code together with
# this challenge token to obtain the full session.

_TOTP_CHALLENGE_EXPIRE_MINUTES = 5


def _create_totp_challenge_token(
    claims: dict,
    *,
    settings: Settings,
) -> tuple[str, datetime]:
    """Create a short-lived HS256 challenge JWT for TOTP 2FA.

    Parameters
    ----------
    claims:
        Payload claims identifying the user (``sub``, ``user_id``, etc.).
    settings:
        Application settings (for signing key).

    Returns
    -------
    tuple[str, datetime]
        ``(encoded_token, expires_at)``
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=_TOTP_CHALLENGE_EXPIRE_MINUTES)
    payload = {
        **claims,
        "type": "totp_challenge",
        "iat": now,
        "exp": expires_at,
    }
    token = pyjwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def _verify_totp_challenge_token(
    token: str,
    *,
    settings: Settings,
) -> dict:
    """Decode and validate a TOTP challenge JWT.

    Parameters
    ----------
    token:
        Encoded challenge JWT string.
    settings:
        Application settings (for signing key).

    Returns
    -------
    dict
        Decoded claims.

    Raises
    ------
    HTTPException
        If the token is expired, invalid, or not a ``totp_challenge`` type.
    """
    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TOTP challenge token has expired. Please re-authenticate.",
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP challenge token.",
        )

    if payload.get("type") != "totp_challenge":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — expected a TOTP challenge token.",
        )

    return payload


# ── POST /auth/magic-link/request ────────────────────────────


@router.post(
    "/magic-link/request",
    response_model=MagicLinkResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a magic link email",
    responses={
        429: {"description": "Rate limit exceeded"},
    },
)
async def request_magic_link(
    body: MagicLinkRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MagicLinkResponse:
    """Request a magic link for non-anonymous reporter login.

    Always returns a success response regardless of whether the email
    matches a report, to prevent user enumeration attacks.

    Rate-limited to 3 requests per email address per hour.
    """
    email_lower = body.email.lower()

    # Rate limiting.
    if not _check_magic_link_rate_limit(email_lower):
        logger.warning(
            "magic_link_rate_limited",
            email=email_lower,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many magic link requests. Please try again later.",
        )

    # Look up the report by case number + email (non-anonymous only).
    # Import here to avoid circular dependency at module level.
    from app.models.report import Report  # noqa: PLC0415

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Report).where(
            Report.case_number == body.case_number,
            Report.is_anonymous.is_(False),
        )
        result = await session.execute(stmt)
        report = result.scalar_one_or_none()

    if report is None:
        # Return success to prevent enumeration — do NOT send email.
        logger.info(
            "magic_link_no_matching_report",
            case_number=body.case_number,
        )
        return MagicLinkResponse()

    # Verify the email matches (encrypted field — compare decrypted value).
    # NOTE: In production the encrypted email comparison requires the
    # decryption service.  For the initial API scaffold we check for the
    # existence of the encrypted value.  Full encrypted-field comparison
    # will be wired when the encryption service is integrated.
    if report.reporter_email_encrypted is None:
        logger.info(
            "magic_link_no_email_on_report",
            case_number=body.case_number,
        )
        return MagicLinkResponse()

    # Create the magic link JWT (15-min expiry via settings).
    token = create_magic_link_token(
        email=email_lower,
        report_id=report.id,
        settings=settings,
    )

    # Build the magic link URL.
    magic_link_url = (
        f"{settings.app_base_url}/mailbox/verify?token={token}"
    )

    # Send the magic link email.
    # NOTE: Full SMTP integration is wired via the notification service
    # in a later subtask.  For now we log the URL for development.
    logger.info(
        "magic_link_created",
        case_number=body.case_number,
        magic_link_url=magic_link_url,
    )

    # TODO: await send_magic_link_email(email_lower, magic_link_url)

    return MagicLinkResponse()


# ── POST /auth/magic-link/verify ─────────────────────────────


@router.post(
    "/magic-link/verify",
    response_model=MagicLinkVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a magic link token",
)
async def verify_magic_link(
    body: MagicLinkVerify,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MagicLinkVerifyResponse:
    """Verify a magic link JWT and create a 24-hour session.

    The magic link token (15-min expiry) is validated.  On success,
    a 24-hour session JWT is issued as an httpOnly cookie and returned
    in the response body.
    """
    # Validate the magic link token (raises HTTPException on failure).
    payload = verify_magic_link_token(body.token, settings=settings)

    email = payload["sub"]
    report_id = payload["report_id"]

    # Fetch the report to return case metadata.
    from app.models.report import Report  # noqa: PLC0415

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Report).where(
            Report.id == report_id,
            Report.is_anonymous.is_(False),
        )
        result = await session.execute(stmt)
        report = result.scalar_one_or_none()

    if report is None:
        logger.warning(
            "magic_link_verify_report_not_found",
            report_id=report_id,
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Report not found or access denied.",
        )

    # Create a 24-hour session token.
    session_claims = {
        "sub": email,
        "report_id": str(report.id),
        "case_number": report.case_number,
        "type": "reporter_session",
    }
    session_token, expires_at = _create_session_token(
        session_claims,
        settings=settings,
    )

    # Set httpOnly session cookie.
    _set_session_cookie(response, session_token)

    logger.info(
        "magic_link_verified",
        case_number=report.case_number,
        email=email,
    )

    return MagicLinkVerifyResponse(
        access_token=session_token,
        expires_at=expires_at,
        case_number=report.case_number,
        channel=report.channel,
        status=report.status,
    )


# ── Redis helpers for OIDC PKCE/State ─────────────────────────

_OIDC_STATE_PREFIX = "oidc:state:"
_OIDC_STATE_TTL = 600  # 10 minutes


async def _redis_client(settings: Settings) -> aioredis.Redis:
    """Return a short-lived Redis client for OIDC state storage."""
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


# ── GET /auth/oidc/login ──────────────────────────────────────


@router.get(
    "/oidc/login",
    status_code=status.HTTP_200_OK,
    summary="Initiate OIDC login (returns authorization URL)",
)
async def oidc_login_initiate(
    redirect_uri: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Initiate the OIDC Authorization Code Flow with PKCE.

    Generates a PKCE code_verifier/code_challenge pair and a random
    state parameter.  Both are stored in Redis (keyed by state) so
    the callback endpoint can retrieve and validate them.

    Returns the full authorization URL for the frontend to redirect to.
    """
    url, state, code_verifier = await build_authorization_url(
        redirect_uri=redirect_uri,
        settings=settings,
    )

    # Store state → code_verifier mapping in Redis
    redis = await _redis_client(settings)
    try:
        await redis.set(
            f"{_OIDC_STATE_PREFIX}{state}",
            code_verifier,
            ex=_OIDC_STATE_TTL,
        )
    finally:
        await redis.aclose()

    return {"authorization_url": url, "state": state}


# ── POST /auth/oidc/callback ────────────────────────────────


@router.post(
    "/oidc/callback",
    response_model=OIDCTokenResponse | OIDCTwoFactorChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="OIDC authorization code callback",
    responses={
        200: {
            "description": (
                "Full session token (no 2FA) or a TOTP challenge "
                "(when the user has 2FA enabled)."
            ),
        },
    },
)
async def oidc_callback(
    body: OIDCCallbackRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OIDCTokenResponse | OIDCTwoFactorChallengeResponse:
    """Handle the OIDC Authorization Code callback for admin login.

    Exchanges the authorization code for tokens via the Entra ID
    token endpoint, validates the ID token against the JWKS endpoint,
    looks up the user in the database, and creates a session.

    The ``code_verifier`` and ``state`` are retrieved from Redis
    where they were stored by the ``/oidc/login`` initiation endpoint.
    """
    # ── Validate state and retrieve PKCE verifier from Redis ─────
    if not body.state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OIDC state parameter.",
        )

    redis = await _redis_client(settings)
    try:
        redis_key = f"{_OIDC_STATE_PREFIX}{body.state}"
        code_verifier = await redis.get(redis_key)
        if code_verifier is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OIDC state parameter.",
            )
        # Delete after use (one-time)
        await redis.delete(redis_key)
    finally:
        await redis.aclose()

    # Exchange the authorization code for tokens with the real PKCE verifier.
    try:
        token_response = await exchange_code_for_tokens(
            code=body.code,
            redirect_uri=body.redirect_uri,
            code_verifier=code_verifier,
            settings=settings,
        )
    except RuntimeError as exc:
        logger.error("oidc_token_exchange_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC token exchange failed.",
        )

    # Validate the ID token.
    id_token_raw = token_response.get("id_token")
    if not id_token_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC response missing id_token.",
        )

    try:
        id_claims = await validate_id_token(
            id_token_raw,
            settings=settings,
        )
    except ValueError as exc:
        logger.error("oidc_id_token_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token validation failed.",
        )

    # Extract user identity from the ID token claims.
    oidc_subject = id_claims.get("sub")
    email = id_claims.get("email") or id_claims.get("preferred_username")
    display_name = id_claims.get("name", "")

    if not oidc_subject or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token missing required claims (sub, email).",
        )

    # Look up the user in the database by OIDC subject.
    # Uses the admin (superuser) session factory to bypass RLS,
    # because this is a cross-tenant lookup where the tenant is
    # not yet known.
    from app.models.user import User  # noqa: PLC0415

    admin_factory = get_admin_session_factory()
    async with admin_factory() as session:
        stmt = select(User).where(User.oidc_subject == oidc_subject)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None:
        logger.warning(
            "oidc_callback_user_not_found",
            oidc_subject=oidc_subject,
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not registered in the system.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    # ── 2FA gate: if user has TOTP enabled, issue a challenge ──
    if user.totp_enabled:
        challenge_claims = {
            "sub": oidc_subject,
            "user_id": str(user.id),
            "email": email,
            "role": user.role.value,
            "tenant_id": str(user.tenant_id),
            "display_name": user.display_name or display_name,
        }
        challenge_token, challenge_expires = _create_totp_challenge_token(
            challenge_claims,
            settings=settings,
        )

        logger.info(
            "oidc_login_2fa_required",
            user_email=email,
        )

        return OIDCTwoFactorChallengeResponse(
            challenge_token=challenge_token,
            expires_at=challenge_expires,
        )

    # Update last login timestamp (set RLS context first).
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        stmt_update = (
            select(User).where(User.id == user.id)
        )
        result = await session.execute(stmt_update)
        db_user = result.scalar_one()
        db_user.last_login_at = datetime.now(UTC)
        await session.commit()

    # Create a 24-hour session token for the admin.
    session_claims = {
        "sub": oidc_subject,
        "user_id": str(user.id),
        "email": email,
        "role": user.role.value,
        "tenant_id": str(user.tenant_id),
        "type": "admin_session",
    }
    session_token, expires_at = _create_session_token(
        session_claims,
        settings=settings,
    )

    # Set httpOnly session cookie.
    _set_session_cookie(response, session_token)

    logger.info(
        "oidc_login_success",
        user_email=email,
        role=user.role.value,
    )

    return OIDCTokenResponse(
        access_token=session_token,
        expires_at=expires_at,
        user_id=user.id,
        email=email,
        display_name=user.display_name or display_name,
        role=user.role.value,
    )


# ── POST /auth/2fa-check ──────────────────────────────────────
# Called by the frontend after OIDC authentication completes to
# determine whether the user must complete a TOTP 2FA challenge.
# This replaces the attempt to read challenge tokens from OIDC
# profile claims (which is architecturally impossible because
# Entra ID cannot include per-login challenge tokens as claims).


@router.post(
    "/2fa-check",
    response_model=TwoFactorCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check whether the authenticated user needs TOTP 2FA",
    responses={
        200: {"description": "2FA status with optional challenge token"},
        401: {"description": "Not authenticated"},
    },
)
async def two_factor_check(
    user=Security(get_current_user, scopes=[]),
    settings: Annotated[Settings, Depends(get_settings)] = ...,
) -> TwoFactorCheckResponse:
    """Check whether the current OIDC-authenticated user needs 2FA.

    Called by the frontend immediately after OIDC login completes.
    If the user has TOTP enabled, returns a short-lived challenge
    token that must be submitted with a valid TOTP code to
    ``POST /auth/totp/challenge`` before the user can proceed.

    If TOTP is not enabled, returns ``requires_2fa=False``.
    """
    if not user.totp_enabled:
        return TwoFactorCheckResponse(requires_2fa=False)

    # Build the challenge token with the same claims as the OIDC
    # callback flow, so the totp/challenge endpoint works identically.
    challenge_claims = {
        "sub": user.oidc_subject or str(user.id),
        "user_id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "tenant_id": str(user.tenant_id),
        "display_name": user.display_name or user.email,
    }
    challenge_token, challenge_expires = _create_totp_challenge_token(
        challenge_claims,
        settings=settings,
    )

    logger.info(
        "2fa_check_challenge_issued",
        user_email=user.email,
    )

    return TwoFactorCheckResponse(
        requires_2fa=True,
        challenge_token=challenge_token,
        expires_at=challenge_expires,
    )


# ── POST /auth/totp/challenge ───────────────────────────────


@router.post(
    "/totp/challenge",
    response_model=OIDCTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete TOTP 2FA challenge during OIDC login",
    responses={
        400: {"description": "Invalid or missing TOTP code"},
        401: {"description": "Invalid or expired challenge token"},
    },
)
async def totp_challenge(
    body: TOTPChallengeRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OIDCTokenResponse:
    """Complete the TOTP two-factor authentication challenge.

    After OIDC login returns an ``OIDCTwoFactorChallengeResponse``,
    the frontend submits the 6-digit TOTP code together with the
    challenge token.  On success, a full 24-hour session JWT is
    issued as an httpOnly cookie and returned in the response body.

    Accepts either a standard 6-digit TOTP code or a single-use
    backup code.
    """
    # Validate the challenge token.
    claims = _verify_totp_challenge_token(
        body.challenge_token,
        settings=settings,
    )

    user_id = claims.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid challenge token — missing user identity.",
        )

    # Look up the user from the challenge token claims.
    from app.models.user import User  # noqa: PLC0415

    admin_factory = get_admin_session_factory()
    async with admin_factory() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account deactivated.",
        )

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP 2FA is not enabled for this user.",
        )

    # Verify the TOTP code against the user's secret.
    code_valid = verify_totp_code(
        user.totp_secret,
        body.code,
        last_used_at=user.totp_last_used_at,
    )

    # If TOTP code fails, try backup codes as fallback.
    backup_used = False
    if not code_valid and user.totp_backup_codes_hash:
        matched_idx = await verify_backup_code(
            body.code,
            user.totp_backup_codes_hash,
        )
        if matched_idx is not None:
            code_valid = True
            backup_used = True
            # Remove the used backup code from the stored hashes.
            remaining_hashes = [
                h for i, h in enumerate(user.totp_backup_codes_hash)
                if i != matched_idx
            ]
            # Update the stored backup codes (remove the used one).
            factory = get_session_factory()
            async with factory() as db_session:
                await db_session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(user.tenant_id)},
                )
                stmt = select(User).where(User.id == user.id)
                result = await db_session.execute(stmt)
                db_user = result.scalar_one()
                db_user.totp_backup_codes_hash = remaining_hashes
                await db_session.commit()

    if not code_valid:
        logger.warning(
            "totp_challenge_invalid_code",
            user_email=claims.get("email"),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )

    # Update last login and totp_last_used_at timestamps.
    now = datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        stmt = select(User).where(User.id == user.id)
        result = await session.execute(stmt)
        db_user = result.scalar_one()
        db_user.last_login_at = now
        db_user.totp_last_used_at = now
        await session.commit()

    # Create the full 24-hour session token.
    session_claims = {
        "sub": claims["sub"],
        "user_id": str(user.id),
        "email": claims["email"],
        "role": claims["role"],
        "tenant_id": str(user.tenant_id),
        "type": "admin_session",
    }
    session_token, expires_at = _create_session_token(
        session_claims,
        settings=settings,
    )

    # Set httpOnly session cookie.
    _set_session_cookie(response, session_token)

    logger.info(
        "oidc_login_2fa_complete",
        user_email=claims["email"],
        role=claims["role"],
        backup_code_used=backup_used,
    )

    return OIDCTokenResponse(
        access_token=session_token,
        expires_at=expires_at,
        user_id=user.id,
        email=claims["email"],
        display_name=claims.get("display_name", ""),
        role=claims["role"],
    )


# ── POST /auth/totp/setup ───────────────────────────────────


@router.post(
    "/totp/setup",
    response_model=TOTPSetupResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate TOTP 2FA setup",
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "TOTP already enabled"},
    },
)
async def totp_setup(
    user=Security(get_current_user, scopes=["totp:manage"]),
    settings: Annotated[Settings, Depends(get_settings)] = ...,
) -> TOTPSetupResponse:
    """Generate a TOTP secret, provisioning URI, and backup codes.

    The secret and backup codes are shown in plaintext exactly once.
    After this call, the user must verify a code via ``POST /auth/totp/verify``
    to activate 2FA.

    If TOTP is already enabled, returns 409 — the user must disable
    it first before re-enrolling.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TOTP 2FA is already enabled. Disable it first to re-enroll.",
        )

    # Generate a fresh TOTP secret and backup codes.
    secret = generate_totp_secret()
    provisioning_uri = generate_totp_provisioning_uri(
        secret=secret,
        email=user.email,
    )
    backup_codes = generate_backup_codes(count=10)
    hashed_codes = await hash_backup_codes(backup_codes)

    # Persist the secret and hashed backup codes (2FA is NOT yet active).
    from app.models.user import User  # noqa: PLC0415

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        stmt = select(User).where(User.id == user.id)
        result = await session.execute(stmt)
        db_user = result.scalar_one()
        db_user.totp_secret = secret
        db_user.totp_backup_codes_hash = hashed_codes
        db_user.totp_enabled = False
        db_user.totp_verified_at = None
        await session.commit()

    logger.info(
        "totp_setup_initiated",
        user_email=user.email,
    )

    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri,
        backup_codes=backup_codes,
    )


# ── POST /auth/totp/verify ──────────────────────────────────


@router.post(
    "/totp/verify",
    response_model=TOTPVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify TOTP code and activate 2FA",
    responses={
        400: {"description": "Invalid TOTP code or no setup in progress"},
        401: {"description": "Not authenticated"},
    },
)
async def totp_verify(
    body: TOTPVerifyRequest,
    user=Security(get_current_user, scopes=["totp:manage"]),
    settings: Annotated[Settings, Depends(get_settings)] = ...,
) -> TOTPVerifyResponse:
    """Verify a 6-digit TOTP code and activate 2FA on the user's account.

    The user must have initiated setup via ``POST /auth/totp/setup``
    first.  On success, the ``totp_enabled`` flag is set and the
    ``totp_verified_at`` timestamp is recorded.

    An audit log entry is created for the TOTP_ENABLED event.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP 2FA is already enabled.",
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No TOTP setup in progress. Call POST /auth/totp/setup first.",
        )

    # Verify the code against the stored secret.
    if not verify_totp_code(user.totp_secret, body.code):
        logger.warning(
            "totp_verify_failed",
            user_email=user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code. Please try again.",
        )

    # Activate 2FA.
    from app.models.user import User  # noqa: PLC0415

    now = datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        stmt = select(User).where(User.id == user.id)
        result = await session.execute(stmt)
        db_user = result.scalar_one()
        db_user.totp_enabled = True
        db_user.totp_verified_at = now
        db_user.totp_last_used_at = now
        await session.commit()

    # Write audit log entry.
    from app.models.audit_log import AuditAction, AuditLog  # noqa: PLC0415

    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        audit_entry = AuditLog(
            tenant_id=user.tenant_id,
            action=AuditAction.TOTP_ENABLED,
            actor_id=user.id,
            actor_type="user",
            resource_type="user",
            resource_id=str(user.id),
            details={"event": "totp_enabled"},
        )
        session.add(audit_entry)
        await session.commit()

    logger.info(
        "totp_enabled",
        user_email=user.email,
    )

    return TOTPVerifyResponse()


# ── POST /auth/totp/disable ─────────────────────────────────


@router.post(
    "/totp/disable",
    response_model=TOTPDisableResponse,
    status_code=status.HTTP_200_OK,
    summary="Disable TOTP 2FA on current user",
    responses={
        400: {"description": "Invalid TOTP code or 2FA not enabled"},
        401: {"description": "Not authenticated"},
    },
)
async def totp_disable(
    body: TOTPDisableRequest,
    user=Security(get_current_user, scopes=["totp:manage"]),
    settings: Annotated[Settings, Depends(get_settings)] = ...,
) -> TOTPDisableResponse:
    """Disable TOTP 2FA on the current user's account.

    Requires a valid 6-digit TOTP code to confirm identity before
    disabling.  Clears all TOTP fields (secret, backup codes,
    timestamps).

    An audit log entry is created for the TOTP_DISABLED event.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP 2FA is not enabled on this account.",
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret not found.",
        )

    # Verify the code to confirm identity.
    if not verify_totp_code(
        user.totp_secret,
        body.code,
        last_used_at=user.totp_last_used_at,
    ):
        logger.warning(
            "totp_disable_invalid_code",
            user_email=user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )

    # Clear all TOTP fields.
    from app.models.user import User  # noqa: PLC0415

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        stmt = select(User).where(User.id == user.id)
        result = await session.execute(stmt)
        db_user = result.scalar_one()
        db_user.totp_secret = None
        db_user.totp_enabled = False
        db_user.totp_verified_at = None
        db_user.totp_last_used_at = None
        db_user.totp_backup_codes_hash = None
        await session.commit()

    # Write audit log entry.
    from app.models.audit_log import AuditAction, AuditLog  # noqa: PLC0415

    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(user.tenant_id)},
        )
        audit_entry = AuditLog(
            tenant_id=user.tenant_id,
            action=AuditAction.TOTP_DISABLED,
            actor_id=user.id,
            actor_type="user",
            resource_type="user",
            resource_id=str(user.id),
            details={"event": "totp_disabled"},
        )
        session.add(audit_entry)
        await session.commit()

    logger.info(
        "totp_disabled",
        user_email=user.email,
    )

    return TOTPDisableResponse()
