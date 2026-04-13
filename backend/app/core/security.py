"""Hinweisgebersystem – Security Module.

Provides:
- **JWT token creation & validation** using ``PyJWT[crypto]`` (RS256 for OIDC,
  HS256 for magic links).
- **bcrypt password hashing** executed in a thread-pool executor so the
  CPU-bound work does not block the async event loop.
- **TOTP verification** using ``pyotp`` (SHA-256, valid_window=1, replay
  prevention via ``totp_last_used_at``).
- **RBAC dependency injection** helpers (``get_current_user``,
  ``require_role``) designed for use with FastAPI's ``Security()`` dependency.

Usage::

    from fastapi import APIRouter, Security, Depends
    from app.core.security import get_current_user, require_role
    from app.models.user import UserRole

    router = APIRouter(prefix="/api/v1/admin/cases", tags=["cases"])

    @router.get("/")
    async def list_cases(
        user = Security(get_current_user, scopes=["cases:read"]),
    ):
        ...

    @router.patch("/{case_id}")
    async def update_case(
        case_id: UUID,
        user = Depends(require_role(UserRole.HANDLER, UserRole.TENANT_ADMIN)),
    ):
        ...
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import bcrypt
import jwt
import pyotp
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    SecurityScopes,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db, get_admin_session_factory

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# ── Bearer token extractor ────────────────────────────────────

# ``auto_error=False`` allows endpoints to differentiate between
# "no token" (anonymous) and "invalid token" (401).
_bearer_scheme = HTTPBearer(auto_error=False)


# ── Password Hashing (bcrypt in thread pool) ──────────────────


async def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt.

    Runs in a thread-pool executor because bcrypt is CPU-bound and
    would otherwise block the async event loop.

    Returns
    -------
    str
        The bcrypt hash as a UTF-8 string suitable for database storage.
    """
    loop = asyncio.get_running_loop()
    hashed: bytes = await loop.run_in_executor(
        None,
        partial(bcrypt.hashpw, password.encode("utf-8"), bcrypt.gensalt()),
    )
    return hashed.decode("utf-8")


async def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Runs in a thread-pool executor to avoid blocking the async loop.
    """
    loop = asyncio.get_running_loop()
    result: bool = await loop.run_in_executor(
        None,
        partial(
            bcrypt.checkpw,
            password.encode("utf-8"),
            hashed.encode("utf-8"),
        ),
    )
    return result


# ── Magic-Link JWT (HS256) ────────────────────────────────────


def create_magic_link_token(
    email: str,
    report_id: UUID,
    *,
    settings: Settings | None = None,
) -> str:
    """Create a short-lived HS256 JWT for magic-link authentication.

    Parameters
    ----------
    email:
        Reporter's email address.
    report_id:
        UUID of the report the magic link grants access to.
    settings:
        Optional settings override (useful for testing).

    Returns
    -------
    str
        Encoded JWT string.
    """
    if settings is None:
        settings = get_settings()

    now = datetime.now(UTC)
    payload = {
        "sub": email,
        "report_id": str(report_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_magic_link_expire_minutes),
        "type": "magic_link",
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_magic_link_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> dict:
    """Decode and validate a magic-link JWT.

    Returns
    -------
    dict
        Decoded payload with ``sub`` (email) and ``report_id``.

    Raises
    ------
    HTTPException (401)
        If the token is expired, tampered, or otherwise invalid.
    """
    if settings is None:
        settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "report_id", "exp", "type"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Magic link has expired.",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("magic_link_token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid magic link token.",
        )

    if payload.get("type") != "magic_link":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    return payload


# ── TOTP Verification (pyotp SHA-256) ─────────────────────────


def verify_totp_code(
    secret: str,
    code: str,
    *,
    last_used_at: datetime | None = None,
) -> bool:
    """Verify a 6-digit TOTP code against the shared secret.

    Uses SHA-256 (not the default SHA-1) and ``valid_window=1`` to
    allow ±30 second clock skew tolerance.

    Replay prevention: if the code's time-step matches
    ``last_used_at``, the code is rejected to prevent reuse within
    the same 30-second window.

    Parameters
    ----------
    secret:
        Base32-encoded TOTP shared secret.
    code:
        6-digit TOTP code to verify.
    last_used_at:
        Timestamp of the last successful TOTP verification.
        Used for replay prevention.

    Returns
    -------
    bool
        ``True`` if the code is valid and not replayed.
    """
    totp = pyotp.TOTP(secret, digest=hashlib.sha256)

    # Replay prevention: reject if the current time-step was already
    # consumed.  ``pyotp.TOTP.verify`` with ``valid_window=1`` accepts
    # codes from the previous, current, and next time steps.  We check
    # if the code corresponds to an already-used time-step.
    if last_used_at is not None:
        # Calculate the time-step that was last used.
        last_timecode = totp.timecode(last_used_at)
        current_timecode = totp.timecode(datetime.now(UTC))
        if current_timecode <= last_timecode:
            return False

    return totp.verify(code, valid_window=1)


def generate_totp_secret() -> str:
    """Generate a new base32-encoded TOTP shared secret.

    Returns
    -------
    str
        32-character base32 secret suitable for use with authenticator apps.
    """
    return pyotp.random_base32()


def generate_totp_provisioning_uri(
    secret: str,
    email: str,
    issuer: str = "Hinweisgebersystem",
) -> str:
    """Generate an ``otpauth://`` provisioning URI for QR code display.

    Parameters
    ----------
    secret:
        Base32-encoded TOTP shared secret.
    email:
        User's email address (used as the account name).
    issuer:
        Application name shown in the authenticator app.

    Returns
    -------
    str
        Full ``otpauth://totp/...`` URI.
    """
    totp = pyotp.TOTP(secret, digest=hashlib.sha256)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate random single-use backup/recovery codes.

    Each code is an 8-character alphanumeric string (uppercase).
    Codes are returned in plaintext for display to the user.

    Parameters
    ----------
    count:
        Number of backup codes to generate.

    Returns
    -------
    list[str]
        Plaintext backup codes.
    """
    import secrets

    return [secrets.token_hex(4).upper() for _ in range(count)]


async def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash a list of backup codes using bcrypt.

    Runs in a thread-pool executor to avoid blocking the async loop.

    Parameters
    ----------
    codes:
        Plaintext backup codes.

    Returns
    -------
    list[str]
        bcrypt-hashed codes.
    """
    loop = asyncio.get_running_loop()
    hashed: list[str] = []
    for code in codes:
        h: bytes = await loop.run_in_executor(
            None,
            partial(bcrypt.hashpw, code.encode("utf-8"), bcrypt.gensalt()),
        )
        hashed.append(h.decode("utf-8"))
    return hashed


async def verify_backup_code(
    code: str,
    hashed_codes: list[str],
) -> int | None:
    """Verify a backup code against the stored hashes.

    Parameters
    ----------
    code:
        Plaintext backup code to check.
    hashed_codes:
        List of bcrypt-hashed backup codes.

    Returns
    -------
    int | None
        Index of the matched code (for removal), or ``None`` if no match.
    """
    loop = asyncio.get_running_loop()
    for idx, hashed in enumerate(hashed_codes):
        matched: bool = await loop.run_in_executor(
            None,
            partial(
                bcrypt.checkpw,
                code.encode("utf-8"),
                hashed.encode("utf-8"),
            ),
        )
        if matched:
            return idx
    return None


# ── OIDC access-token validation (RS256 via JWKS) ────────────


async def _validate_oidc_access_token(
    token: str,
    settings: Settings,
) -> dict:
    """Validate an OIDC access token (or id_token) against the Entra ID
    JWKS endpoint.

    This function delegates to the ``oidc`` module for JWKS key
    retrieval and performs standard JWT validation.

    Returns
    -------
    dict
        Decoded token claims.

    Raises
    ------
    HTTPException (401)
        If validation fails for any reason.
    """
    # Import lazily to avoid circular dependency (oidc imports nothing
    # from security, but keeping the import local is cleaner).
    from app.core.oidc import get_signing_key  # noqa: PLC0415

    try:
        # Decode header to discover the ``kid`` (key ID).
        unverified_header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authorization token.",
        )

    kid = unverified_header.get("kid")
    if kid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header missing 'kid'.",
        )

    # Fetch the appropriate RSA public key from the cached JWKS.
    signing_key = await get_signing_key(kid, settings=settings)
    if signing_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate signing key.",
        )

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience.",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer.",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("oidc_token_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed.",
        )

    return payload


# ── Current-user resolution ───────────────────────────────────
# This is the main dependency used with ``Security()`` in route
# handlers.  It extracts the bearer token, validates it against
# the OIDC JWKS, looks up the user in the database, and returns
# the ``User`` ORM instance.


async def get_current_user(
    request: Request,
    security_scopes: SecurityScopes,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ] = None,
    settings: Settings = Depends(get_settings),
):
    """FastAPI ``Security()`` dependency — resolves the current user.

    Validates the bearer token against the OIDC JWKS endpoint,
    looks up the corresponding ``User`` record, and verifies that
    the user has the required OAuth2 scopes (if any).

    Parameters
    ----------
    security_scopes:
        OAuth2 scopes declared on the route via ``Security(scopes=[...])``.
    credentials:
        Bearer token extracted by ``HTTPBearer``.
    settings:
        Application settings (injected).

    Returns
    -------
    User
        The authenticated, active user.

    Raises
    ------
    HTTPException (401)
        Missing or invalid credentials.
    HTTPException (403)
        User is inactive or lacks required scopes.
    """
    from app.models.user import User  # noqa: PLC0415

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = await _validate_oidc_access_token(
        credentials.credentials,
        settings,
    )

    # Resolve user by OIDC ``sub`` claim.
    oidc_subject = token_data.get("sub")
    if not oidc_subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim.",
        )

    # Open a fresh session for user lookup (not tied to request
    # tenant context — the user table is cross-tenant for
    # system admins but tenant-scoped via RLS for others).
    factory = get_admin_session_factory()
    async with factory() as session:
        stmt = select(User).where(User.oidc_subject == oidc_subject)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None:
        logger.warning(
            "oidc_user_not_found",
            oidc_subject=oidc_subject,
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

    # Cross-tenant check: verify user belongs to the resolved tenant
    # (system_admin is exempt as they operate across tenants).
    request_tenant_id = getattr(request.state, "tenant_id", None)
    if (
        request_tenant_id is not None
        and user.role.value != "system_admin"
        and str(user.tenant_id) != str(request_tenant_id)
    ):
        logger.warning(
            "cross_tenant_access_denied",
            user_tenant=str(user.tenant_id),
            request_tenant=str(request_tenant_id),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    # Scope validation — scopes are mapped from roles.
    if security_scopes.scopes:
        user_scopes = _role_to_scopes(user.role)
        for scope in security_scopes.scopes:
            if scope not in user_scopes:
                logger.warning(
                    "insufficient_scope",
                    user_email=user.email,
                    required=security_scopes.scopes,
                    available=list(user_scopes),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions.",
                )

    return user


# ── Role-based dependency ─────────────────────────────────────
# Use this as ``Depends(require_role(UserRole.HANDLER))`` when you
# don't need OAuth2 scope semantics but want to restrict by role.


def require_role(*allowed_roles):
    """Create a FastAPI dependency that restricts access to specific roles.

    Usage::

        @router.delete("/{id}")
        async def delete_case(
            id: UUID,
            user = Depends(require_role(UserRole.SYSTEM_ADMIN)),
        ):
            ...

    Parameters
    ----------
    *allowed_roles : UserRole
        One or more roles permitted to access the endpoint.

    Returns
    -------
    Callable
        An async dependency function.
    """

    async def _role_checker(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(_bearer_scheme),
        ] = None,
        settings: Settings = Depends(get_settings),
    ):
        from app.models.user import User  # noqa: PLC0415

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = await _validate_oidc_access_token(
            credentials.credentials,
            settings,
        )

        oidc_subject = token_data.get("sub")
        if not oidc_subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing 'sub' claim.",
            )

        factory = get_admin_session_factory()
        async with factory() as session:
            stmt = select(User).where(User.oidc_subject == oidc_subject)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not registered in the system.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated.",
            )

        if user.role not in allowed_roles:
            logger.warning(
                "role_denied",
                user_email=user.email,
                required_roles=[r.value for r in allowed_roles],
                user_role=user.role.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions.",
            )

        return user

    return _role_checker


# ── Role → scope mapping ─────────────────────────────────────
# Scopes are a flat permission model layered on top of the five
# database roles.  This keeps authorization logic in one place
# and allows ``Security(get_current_user, scopes=[...])`` to work
# cleanly without coupling routes to role enums.

_ROLE_SCOPES: dict[str, set[str]] = {
    "system_admin": {
        "cases:read",
        "cases:write",
        "cases:delete",
        "messages:read",
        "messages:write",
        "notes:read",
        "notes:write",
        "users:read",
        "users:write",
        "tenants:read",
        "tenants:write",
        "audit:read",
        "dashboard:read",
        "categories:read",
        "categories:write",
        "labels:read",
        "labels:write",
        "substatuses:read",
        "substatuses:write",
        "custodian:request",
        "custodian:approve",
        "reports:read",
        "totp:manage",
        "pgp:manage",
    },
    "tenant_admin": {
        "cases:read",
        "cases:write",
        "messages:read",
        "messages:write",
        "notes:read",
        "notes:write",
        "users:read",
        "users:write",
        "tenants:read",
        "tenants:write",
        "audit:read",
        "dashboard:read",
        "categories:read",
        "categories:write",
        "labels:read",
        "labels:write",
        "substatuses:read",
        "substatuses:write",
        "custodian:request",
        "custodian:approve",
        "reports:read",
        "totp:manage",
        "pgp:manage",
    },
    "handler": {
        "cases:read",
        "cases:write",
        "messages:read",
        "messages:write",
        "notes:read",
        "notes:write",
        "dashboard:read",
        "categories:read",
        "labels:read",
        "labels:write",
        "substatuses:read",
        "custodian:request",
        "reports:read",
        "totp:manage",
    },
    "reviewer": {
        "cases:read",
        "messages:read",
        "notes:read",
        "dashboard:read",
        "labels:read",
        "totp:manage",
    },
    "auditor": {
        "audit:read",
        "dashboard:read",
        "cases:read",
        "reports:read",
        "labels:read",
        "totp:manage",
    },
}


def _role_to_scopes(role) -> set[str]:
    """Map a ``UserRole`` enum value to the set of granted scopes."""
    return _ROLE_SCOPES.get(role.value, set())
