"""Hinweisgebersystem – Tenant Pydantic Schemas.

Request and response schemas for multi-tenant management endpoints.
Each tenant represents an organisation using the whistleblower platform,
with its own branding, SMTP configuration, language settings, and
data retention periods.

Tenant configuration is stored as JSONB in the database, but the
schema layer provides structured sub-models (``TenantBranding``,
``TenantSMTPConfig``) for validation and documentation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import PaginatedResponse, TimestampSchema, UUIDSchema


# ── Tenant Config Sub-Models ─────────────────────────────────


class TenantBranding(BaseModel):
    """Branding configuration for the tenant's reporter portal."""

    model_config = ConfigDict(str_strip_whitespace=True)

    logo_url: str | None = Field(
        default=None,
        max_length=2048,
        description="URL to the tenant's logo image.",
    )
    primary_color: str | None = Field(
        default=None,
        max_length=7,
        description="Primary brand color (hex, e.g. ``#1a73e8``).",
    )
    accent_color: str | None = Field(
        default=None,
        max_length=7,
        description="Accent / secondary brand color (hex).",
    )

    @field_validator("primary_color", "accent_color")
    @classmethod
    def validate_hex_color(cls, v: str | None) -> str | None:
        """Ensure color values are valid hex strings."""
        if v is not None and not v.startswith("#"):
            msg = "Color must be a hex string starting with '#' (e.g. '#1a73e8')."
            raise ValueError(msg)
        return v


class TenantSMTPConfig(BaseModel):
    """Per-tenant SMTP configuration for outgoing emails."""

    model_config = ConfigDict(str_strip_whitespace=True)

    host: str = Field(
        max_length=255,
        description="SMTP server hostname.",
    )
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port.",
    )
    user: str = Field(
        max_length=255,
        description="SMTP authentication username.",
    )
    password: str = Field(
        max_length=512,
        description="SMTP authentication password.",
    )
    from_address: str = Field(
        max_length=255,
        description="Sender email address (From header).",
    )
    use_tls: bool = Field(
        default=True,
        description="Use STARTTLS for SMTP connection.",
    )


class TenantConfig(BaseModel):
    """Structured tenant configuration stored as JSONB.

    Provides typed access to branding, SMTP, language, and data
    retention settings.
    """

    branding: TenantBranding = Field(
        default_factory=TenantBranding,
        description="Branding settings for the reporter portal.",
    )
    smtp: TenantSMTPConfig | None = Field(
        default=None,
        description="Per-tenant SMTP configuration (falls back to global if not set).",
    )
    languages: list[str] = Field(
        default_factory=lambda: ["de", "en"],
        description="Enabled language codes for this tenant.",
    )
    default_language: str = Field(
        default="de",
        max_length=5,
        description="Fallback language code (ISO 639-1).",
    )
    retention_hinschg_years: int = Field(
        default=3,
        ge=1,
        le=30,
        description="Data retention period for HinSchG reports (years).",
    )
    retention_lksg_years: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Data retention period for LkSG reports (years).",
    )


# ── Tenant Create ─────────────────────────────────────────────


class TenantCreate(BaseModel):
    """Schema for creating a new tenant (system admin only)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str = Field(
        min_length=2,
        max_length=63,
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
        description=(
            "URL-safe tenant identifier used in subdomain / path routing.  "
            "Lowercase alphanumeric and hyphens only."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Organisation display name.",
    )
    config: TenantConfig = Field(
        default_factory=TenantConfig,
        description="Tenant-specific configuration (branding, SMTP, etc.).",
    )


# ── Tenant Update ─────────────────────────────────────────────


class TenantUpdate(BaseModel):
    """Schema for updating an existing tenant.

    All fields are optional — only provided fields will be updated.
    The ``version`` field is required for optimistic locking.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated organisation display name.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the tenant.",
    )
    config: TenantConfig | None = Field(
        default=None,
        description="Updated tenant configuration.",
    )
    version: int = Field(
        description="Current version for optimistic locking (must match DB).",
    )


# ── Tenant Response ───────────────────────────────────────────


class TenantResponse(UUIDSchema, TimestampSchema):
    """Full tenant response for system admin views."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    is_active: bool
    config: TenantConfig
    version: int


# ── Tenant Public Info (reporter-facing) ──────────────────────


class TenantPublicInfo(BaseModel):
    """Minimal tenant information exposed to the reporter portal.

    Does not include internal configuration details (SMTP, DEK, etc.).
    """

    model_config = ConfigDict(from_attributes=True)

    slug: str = Field(description="Tenant slug for URL routing.")
    name: str = Field(description="Organisation display name.")
    branding: TenantBranding = Field(
        default_factory=TenantBranding,
        description="Branding configuration for the reporter portal.",
    )
    languages: list[str] = Field(
        default_factory=lambda: ["de", "en"],
        description="Enabled languages for the reporter portal.",
    )
    default_language: str = Field(
        default="de",
        description="Default/fallback language.",
    )


# ── Paginated Tenant List ─────────────────────────────────────


class TenantListResponse(PaginatedResponse[TenantResponse]):
    """Paginated list of tenants for system admin views."""

    pass
