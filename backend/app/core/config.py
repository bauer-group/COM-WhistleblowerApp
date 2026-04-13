"""Hinweisgebersystem – Application Configuration.

Centralised Pydantic Settings class that reads all environment variables.
Uses ``SettingsConfigDict`` with ``env_file=".env"`` and
``env_nested_delimiter="__"`` as specified by the project patterns.
No ``env_prefix`` is used -- field names match env var names directly
(case-insensitive by default in pydantic-settings).

Usage::

    from app.core.config import settings

    db_url = settings.database_url
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        # Case-insensitive matching is the default for pydantic-settings,
        # so DATABASE_URL matches database_url etc.
    )

    # ── PostgreSQL ─────────────────────────────────────────────
    database_url: str = Field(
        description="Async SQLAlchemy URL for the application role (app_user).",
    )
    database_admin_url: str = Field(
        description="Async SQLAlchemy URL for the superuser role (migrations only).",
    )

    # ── OIDC – Microsoft Entra ID ──────────────────────────────
    oidc_issuer: str = Field(
        description="OIDC issuer URL, e.g. https://login.microsoftonline.com/{tenant}/v2.0",
    )
    oidc_client_id: str = Field(description="Entra ID application (client) ID.")
    oidc_client_secret: str = Field(description="Entra ID client secret.")

    # ── Encryption ─────────────────────────────────────────────
    encryption_master_key: str = Field(
        description="256-bit hex-encoded master key for envelope encryption.",
    )

    # ── SMTP ───────────────────────────────────────────────────
    smtp_host: str = Field(description="SMTP server hostname.")
    smtp_port: int = Field(default=587, description="SMTP server port.")
    smtp_user: str = Field(description="SMTP authentication username.")
    smtp_password: str = Field(description="SMTP authentication password.")
    smtp_from: str = Field(
        default="noreply@example.com",
        description="Sender address for outgoing emails.",
    )

    # ── MinIO (S3-compatible storage) ──────────────────────────
    s3_endpoint: str = Field(
        default="minio:9000",
        description="MinIO endpoint (host:port).",
    )
    s3_access_key: str = Field(description="MinIO access key.")
    s3_secret_key: str = Field(description="MinIO secret key.")
    s3_bucket: str = Field(
        default="attachments",
        description="Default bucket for file attachments.",
    )
    s3_secure: bool = Field(
        default=False,
        description="Use TLS for MinIO connections.",
    )

    # ── Redis ──────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL.",
    )

    # ── CORS ───────────────────────────────────────────────────
    cors_origins: str = Field(
        default="",
        description="Comma-separated list of allowed CORS origins.",
    )

    # ── hCaptcha ───────────────────────────────────────────────
    hcaptcha_secret: str = Field(description="hCaptcha secret key for server verification.")
    hcaptcha_sitekey: str = Field(description="hCaptcha site key for the frontend widget.")

    # ── JWT (Magic Links) ──────────────────────────────────────
    jwt_secret_key: str = Field(
        description="Secret key for signing magic-link JWTs.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm for magic links.",
    )
    jwt_magic_link_expire_minutes: int = Field(
        default=15,
        description="Magic link token expiry in minutes.",
    )

    # ── Application ────────────────────────────────────────────
    debug: bool = Field(
        default=False,
        description="Enable debug/development mode.  Must be False in production.",
    )
    app_base_url: str = Field(
        default="https://localhost",
        description="Public base URL (used in emails, magic links).",
    )
    log_level: str = Field(
        default="info",
        description="Logging level (debug, info, warning, error, critical).",
    )
    allowed_hosts: list[str] = Field(
        default=["*"],
        description="Allowed Host header values for TrustedHostMiddleware.",
    )

    # ── Database pool tuning ───────────────────────────────────
    db_pool_size: int = Field(
        default=10,
        description="SQLAlchemy async engine connection pool size.",
    )
    db_pool_max_overflow: int = Field(
        default=20,
        description="Max overflow connections beyond pool_size.",
    )
    db_pool_recycle: int = Field(
        default=3600,
        description="Recycle connections after N seconds.",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings.

    Using ``lru_cache`` ensures the .env file is read only once and the
    same ``Settings`` instance is reused for all ``Depends(get_settings)``
    injections.
    """
    return Settings()  # type: ignore[call-arg]


# Module-level convenience alias
settings: Settings = get_settings()
