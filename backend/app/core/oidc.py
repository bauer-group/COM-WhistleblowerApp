"""Hinweisgebersystem – OIDC Module (Microsoft Entra ID).

Provides:
- **JWKS endpoint discovery** via httpx with aggressive caching for
  Entra ID outage resilience.
- **RSA public key retrieval** by ``kid`` (key ID) for JWT signature
  verification.
- **Authorization Code Flow with PKCE** helpers (code verifier/challenge
  generation, token exchange).
- **OpenID Connect configuration discovery** from the well-known endpoint.

The module caches JWKS keys in memory with a configurable TTL (default
24 hours) and falls back to stale cached keys if the JWKS endpoint is
unreachable, providing resilience against transient OIDC provider outages.

Usage::

    from app.core.oidc import get_signing_key, build_authorization_url

    # In security.py — get RSA key for JWT validation
    key = await get_signing_key(kid="abc123")

    # In auth router — start Authorization Code Flow with PKCE
    url, state, verifier = await build_authorization_url(
        redirect_uri="https://admin.example.com/callback",
    )
"""

from __future__ import annotations

import hashlib
import secrets
import time
from base64 import urlsafe_b64encode
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import structlog
from jwt import PyJWK

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

# ── JWKS Cache ────────────────────────────────────────────────
# Keys are cached aggressively (default: 24h) to survive OIDC
# provider outages.  A background refresh is attempted when the
# cache is past its soft TTL; stale keys are served if the
# refresh fails.

_JWKS_CACHE_TTL_SECONDS: int = 86_400  # 24 hours — hard maximum
_JWKS_SOFT_TTL_SECONDS: int = 3_600  # 1 hour — triggers background refresh

_jwks_cache: dict[str, Any] = {
    "keys": {},  # kid → PyJWK mapping
    "raw_keys": [],  # raw JWKS key dicts
    "fetched_at": 0.0,
    "oidc_config": None,  # OpenID Connect discovery document
    "oidc_config_fetched_at": 0.0,
}


# ── OpenID Connect Discovery ─────────────────────────────────


def _well_known_url(issuer: str) -> str:
    """Derive the OpenID Connect discovery URL from the issuer.

    For Microsoft Entra ID the issuer is typically:
    ``https://login.microsoftonline.com/{tenant_id}/v2.0``

    The well-known configuration is at:
    ``https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration``
    """
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


async def get_oidc_config(
    *,
    settings: Settings | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch and cache the OpenID Connect discovery document.

    Returns
    -------
    dict
        The OpenID Connect configuration containing ``jwks_uri``,
        ``authorization_endpoint``, ``token_endpoint``, etc.
    """
    if settings is None:
        settings = get_settings()

    now = time.monotonic()
    cached_config = _jwks_cache.get("oidc_config")
    cached_at = _jwks_cache.get("oidc_config_fetched_at", 0.0)

    if (
        cached_config is not None
        and not force_refresh
        and (now - cached_at) < _JWKS_CACHE_TTL_SECONDS
    ):
        return cached_config

    url = _well_known_url(settings.oidc_issuer)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            config = response.json()

        _jwks_cache["oidc_config"] = config
        _jwks_cache["oidc_config_fetched_at"] = now
        logger.info("oidc_config_refreshed", issuer=settings.oidc_issuer)
        return config

    except (httpx.HTTPError, Exception) as exc:
        logger.error(
            "oidc_config_fetch_failed",
            error=str(exc),
            url=url,
        )
        # Fall back to stale cached config if available.
        if cached_config is not None:
            logger.warning("oidc_config_using_stale_cache")
            return cached_config
        raise RuntimeError(
            f"Failed to fetch OIDC configuration from {url}: {exc}"
        ) from exc


# ── JWKS Key Fetching ─────────────────────────────────────────


async def _fetch_jwks(
    jwks_uri: str,
) -> list[dict[str, Any]]:
    """Fetch raw JWKS key set from the provider.

    Parameters
    ----------
    jwks_uri:
        The JWKS URI from the OIDC discovery document.

    Returns
    -------
    list[dict]
        List of raw JWK key dictionaries.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_uri)
        response.raise_for_status()
        data = response.json()
    return data.get("keys", [])


async def _refresh_jwks(
    *,
    settings: Settings | None = None,
) -> dict[str, PyJWK]:
    """Refresh the JWKS cache from the provider.

    Returns
    -------
    dict[str, PyJWK]
        Mapping of ``kid`` → ``PyJWK`` objects.
    """
    if settings is None:
        settings = get_settings()

    oidc_config = await get_oidc_config(settings=settings)
    jwks_uri = oidc_config.get("jwks_uri")
    if not jwks_uri:
        raise RuntimeError("OIDC configuration missing 'jwks_uri'.")

    raw_keys = await _fetch_jwks(jwks_uri)
    key_map: dict[str, PyJWK] = {}

    for key_data in raw_keys:
        kid = key_data.get("kid")
        if kid is None:
            continue
        try:
            key_map[kid] = PyJWK(key_data)
        except Exception as exc:
            logger.warning(
                "jwks_key_parse_failed",
                kid=kid,
                error=str(exc),
            )
            continue

    now = time.monotonic()
    _jwks_cache["keys"] = key_map
    _jwks_cache["raw_keys"] = raw_keys
    _jwks_cache["fetched_at"] = now

    logger.info(
        "jwks_cache_refreshed",
        key_count=len(key_map),
        kids=list(key_map.keys()),
    )
    return key_map


async def get_signing_key(
    kid: str,
    *,
    settings: Settings | None = None,
) -> Any | None:
    """Retrieve the RSA public key for the given ``kid``.

    This is the primary interface used by ``security.py`` to obtain the
    key for JWT signature verification.

    Strategy:
    1. If the key is in cache and the cache is fresh → return it.
    2. If the key is NOT in cache → force refresh from JWKS endpoint.
    3. If the refresh fails → fall back to stale cached key.
    4. If the key cannot be found → return ``None``.

    Parameters
    ----------
    kid:
        The ``kid`` (key ID) from the JWT header.
    settings:
        Application settings (optional, resolved from config if ``None``).

    Returns
    -------
    RSA public key suitable for ``jwt.decode()``, or ``None``.
    """
    if settings is None:
        settings = get_settings()

    now = time.monotonic()
    cached_keys = _jwks_cache.get("keys", {})
    fetched_at = _jwks_cache.get("fetched_at", 0.0)
    cache_age = now - fetched_at

    # 1. Cache hit — key is known and cache is within hard TTL.
    if kid in cached_keys and cache_age < _JWKS_CACHE_TTL_SECONDS:
        # If past soft TTL, trigger a refresh attempt in the background
        # for next time, but return the cached key immediately.
        if cache_age > _JWKS_SOFT_TTL_SECONDS:
            try:
                await _refresh_jwks(settings=settings)
            except Exception:
                logger.warning("jwks_background_refresh_failed")
        return cached_keys[kid].key

    # 2. Cache miss or cache expired — try to refresh.
    try:
        refreshed = await _refresh_jwks(settings=settings)
        if kid in refreshed:
            return refreshed[kid].key
    except Exception as exc:
        logger.error("jwks_refresh_failed", error=str(exc))

    # 3. Fall back to stale cache.
    if kid in cached_keys:
        logger.warning(
            "jwks_using_stale_key",
            kid=kid,
            cache_age_seconds=int(cache_age),
        )
        return cached_keys[kid].key

    # 4. Key not found.
    logger.warning("jwks_key_not_found", kid=kid)
    return None


# ── Authorization Code Flow with PKCE ─────────────────────────
# These helpers are used by the ``/api/v1/auth/oidc/login`` endpoint
# to initiate the OIDC login flow and by the callback endpoint to
# exchange the authorization code for tokens.


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and challenge.

    Returns
    -------
    tuple[str, str]
        ``(code_verifier, code_challenge)`` where the challenge is
        the S256 hash of the verifier.
    """
    # Code verifier: 43-128 characters from unreserved characters.
    # Using 64 bytes → 86 base64url characters (within range).
    verifier_bytes = secrets.token_bytes(64)
    code_verifier = (
        urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")
    )

    # Code challenge: BASE64URL(SHA256(code_verifier))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


def generate_state() -> str:
    """Generate a cryptographically random state parameter.

    Returns
    -------
    str
        A URL-safe random string for CSRF protection.
    """
    return secrets.token_urlsafe(32)


async def build_authorization_url(
    redirect_uri: str,
    *,
    settings: Settings | None = None,
    scopes: list[str] | None = None,
    extra_params: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Build the OIDC authorization URL for login redirect.

    Parameters
    ----------
    redirect_uri:
        The callback URL registered in Entra ID.
    settings:
        Application settings (optional).
    scopes:
        OAuth2 scopes to request.  Defaults to ``["openid", "profile", "email"]``.
    extra_params:
        Additional query parameters for the authorization request.

    Returns
    -------
    tuple[str, str, str]
        ``(authorization_url, state, code_verifier)`` — the state and
        verifier must be stored server-side (e.g. in Redis) for
        validation during the callback.
    """
    if settings is None:
        settings = get_settings()

    oidc_config = await get_oidc_config(settings=settings)
    authorization_endpoint = oidc_config.get("authorization_endpoint")
    if not authorization_endpoint:
        raise RuntimeError(
            "OIDC configuration missing 'authorization_endpoint'."
        )

    if scopes is None:
        scopes = ["openid", "profile", "email"]

    state = generate_state()
    code_verifier, code_challenge = generate_pkce_pair()

    params: dict[str, str] = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "response_mode": "query",
    }

    if extra_params:
        params.update(extra_params)

    url = f"{authorization_endpoint}?{urlencode(params)}"
    return url, state, code_verifier


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    Performs the token exchange at the OIDC provider's token endpoint
    using the Authorization Code Flow with PKCE.

    Parameters
    ----------
    code:
        The authorization code from the callback.
    redirect_uri:
        The same redirect URI used in the authorization request.
    code_verifier:
        The PKCE code verifier generated during the authorization request.
    settings:
        Application settings (optional).

    Returns
    -------
    dict
        Token response containing ``access_token``, ``id_token``,
        ``refresh_token`` (if granted), ``expires_in``, etc.

    Raises
    ------
    RuntimeError
        If the token exchange fails.
    """
    if settings is None:
        settings = get_settings()

    oidc_config = await get_oidc_config(settings=settings)
    token_endpoint = oidc_config.get("token_endpoint")
    if not token_endpoint:
        raise RuntimeError("OIDC configuration missing 'token_endpoint'.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        error_body = response.text
        logger.error(
            "oidc_token_exchange_failed",
            status_code=response.status_code,
            error=error_body,
        )
        raise RuntimeError(
            f"Token exchange failed (HTTP {response.status_code}): {error_body}"
        )

    token_data = response.json()
    logger.info("oidc_token_exchange_success")
    return token_data


async def validate_id_token(
    id_token: str,
    *,
    settings: Settings | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Validate an OIDC ID token.

    Performs full JWT validation including signature verification
    against the JWKS endpoint, issuer, audience, and optionally
    nonce verification.

    Parameters
    ----------
    id_token:
        The raw ID token string.
    settings:
        Application settings (optional).
    nonce:
        Expected nonce value (if one was sent in the authorization request).

    Returns
    -------
    dict
        Decoded ID token claims.

    Raises
    ------
    ValueError
        If the token is invalid.
    """
    if settings is None:
        settings = get_settings()

    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Malformed ID token: {exc}") from exc

    kid = unverified_header.get("kid")
    if kid is None:
        raise ValueError("ID token header missing 'kid'.")

    signing_key = await get_signing_key(kid, settings=settings)
    if signing_key is None:
        raise ValueError(f"Signing key not found for kid={kid!r}.")

    try:
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"ID token validation failed: {exc}") from exc

    # Verify nonce if provided (prevents replay attacks).
    if nonce is not None and claims.get("nonce") != nonce:
        raise ValueError("ID token nonce mismatch.")

    return claims


# ── Cache Management ──────────────────────────────────────────


def clear_jwks_cache() -> None:
    """Clear the in-memory JWKS cache.

    Useful for testing or when key rotation is detected.
    """
    _jwks_cache["keys"] = {}
    _jwks_cache["raw_keys"] = []
    _jwks_cache["fetched_at"] = 0.0
    _jwks_cache["oidc_config"] = None
    _jwks_cache["oidc_config_fetched_at"] = 0.0
    logger.info("jwks_cache_cleared")
