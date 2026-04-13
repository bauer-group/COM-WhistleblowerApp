"""Hinweisgebersystem – Admin Tenant Management API Endpoints.

Provides:
- **GET /admin/tenants** — Paginated tenant list with search and
  active status filter.
- **POST /admin/tenants** — Create a new tenant with DEK generation
  and default category seeding.
- **GET /admin/tenants/{tenant_id}** — Get full tenant detail
  including configuration.
- **PATCH /admin/tenants/{tenant_id}** — Update tenant name,
  branding, config, or activation status with optimistic locking.
- **GET /admin/tenants/{tenant_id}/i18n** — Get language/i18n
  configuration for a tenant.
- **PUT /admin/tenants/{tenant_id}/i18n** — Update language/i18n
  configuration (enabled languages, default language).
- **GET /admin/tenants/{tenant_id}/channels** — Get channel
  activation status (HinSchG, LkSG).
- **PUT /admin/tenants/{tenant_id}/channels** — Update channel
  activation (enable/disable HinSchG and LkSG channels).

All endpoints require OIDC-authenticated admin users with appropriate
scopes.  Tenant management is a system-level operation — only
SYSTEM_ADMIN and TENANT_ADMIN roles have access.

Usage::

    from app.api.v1.admin_tenants import router as admin_tenants_router
    api_v1_router.include_router(admin_tenants_router)
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_dek
from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_tenant_db
from app.schemas.common import PaginationParams
from app.schemas.tenant import (
    TenantConfig,
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)
from app.services.tenant_service import TenantService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])


# ── Request/Response schemas for sub-endpoints ──────────────
# Inline schemas for i18n config and channel activation that are
# specific to these admin endpoints.


class I18nConfigResponse(BaseModel):
    """Language/i18n configuration for a tenant."""

    model_config = ConfigDict(frozen=True)

    languages: list[str] = Field(
        description="Enabled ISO 639-1 language codes.",
    )
    default_language: str = Field(
        description="Fallback language code.",
    )


class I18nConfigUpdate(BaseModel):
    """Request body for updating tenant i18n configuration."""

    model_config = ConfigDict(str_strip_whitespace=True)

    languages: list[str] = Field(
        min_length=1,
        description="Enabled ISO 639-1 language codes (at least one required).",
    )
    default_language: str = Field(
        max_length=5,
        description=(
            "Fallback language code. Must be included in the "
            "``languages`` list."
        ),
    )
    version: int = Field(
        description="Current version for optimistic locking (must match DB).",
    )


class ChannelActivationResponse(BaseModel):
    """Channel activation status for a tenant."""

    model_config = ConfigDict(frozen=True)

    hinschg_enabled: bool = Field(
        default=True,
        description="Whether the HinSchG (internal whistleblowing) channel is enabled.",
    )
    lksg_enabled: bool = Field(
        default=True,
        description="Whether the LkSG (supply chain complaints) channel is enabled.",
    )


class ChannelActivationUpdate(BaseModel):
    """Request body for updating channel activation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    hinschg_enabled: bool | None = Field(
        default=None,
        description="Enable or disable the HinSchG channel.",
    )
    lksg_enabled: bool | None = Field(
        default=None,
        description="Enable or disable the LkSG channel.",
    )
    version: int = Field(
        description="Current version for optimistic locking (must match DB).",
    )


# ── GET /admin/tenants ───────────────────────────────────────


@router.get(
    "",
    response_model=TenantListResponse,
    status_code=status.HTTP_200_OK,
    summary="List tenants with filters and pagination",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_tenants(
    user=Security(get_current_user, scopes=["tenants:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    # ── Pagination ───────────────────────────────────────────
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)."
    ),
    # ── Filters ──────────────────────────────────────────────
    is_active: bool | None = Query(
        default=None, description="Filter by active/inactive status."
    ),
    search: str | None = Query(
        default=None,
        max_length=500,
        description="Search on slug and name (case-insensitive).",
    ),
) -> TenantListResponse:
    """List all tenants with optional filtering and pagination.

    Supports filtering by active status and free-text search on
    slug and name.

    Requires ``tenants:read`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    pagination = PaginationParams(page=page, page_size=page_size)
    tenant_service = TenantService(db)

    tenants, meta = await tenant_service.list_tenants(
        pagination=pagination,
        is_active=is_active,
        search=search,
    )

    items = [TenantResponse.model_validate(t) for t in tenants]

    logger.info(
        "admin_tenants_listed",
        user_email=user.email,
        total=meta.total,
        page=page,
    )

    return TenantListResponse(items=items, pagination=meta)


# ── POST /admin/tenants ──────────────────────────────────────


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "Tenant slug already exists"},
    },
)
async def create_tenant(
    body: TenantCreate,
    user=Security(get_current_user, scopes=["tenants:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TenantResponse:
    """Create a new tenant with default categories and DEK generation.

    A fresh Data Encryption Key (DEK) is generated and encrypted with
    the application master key via envelope encryption.  Default report
    categories are seeded for all enabled languages.

    Requires ``tenants:write`` scope (SYSTEM_ADMIN only).
    """
    from app.core.config import settings

    tenant_service = TenantService(db)

    # Generate a new DEK and encrypt it with the master key
    raw_dek = __import__("os").urandom(32).hex()
    dek_ciphertext = encrypt_dek(raw_dek, settings.MASTER_KEY)

    try:
        tenant = await tenant_service.create_tenant(
            body,
            dek_ciphertext=dek_ciphertext,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    logger.info(
        "admin_tenant_created",
        tenant_slug=tenant.slug,
        tenant_id=str(tenant.id),
        created_by=user.email,
    )

    return TenantResponse.model_validate(tenant)


# ── GET /admin/tenants/{tenant_id} ──────────────────────────


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full tenant detail",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def get_tenant(
    tenant_id: uuid.UUID,
    user=Security(get_current_user, scopes=["tenants:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TenantResponse:
    """Get a single tenant's full detail including configuration.

    Returns the complete tenant record with branding, SMTP config,
    language settings, retention periods, and version number for
    optimistic locking.

    Requires ``tenants:read`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    logger.info(
        "admin_tenant_viewed",
        tenant_id=str(tenant_id),
        user_email=user.email,
    )

    return TenantResponse.model_validate(tenant)


# ── PATCH /admin/tenants/{tenant_id} ────────────────────────


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Update tenant name, branding, config, or status",
    responses={
        404: {"description": "Tenant not found"},
        409: {"description": "Optimistic locking conflict"},
    },
)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    user=Security(get_current_user, scopes=["tenants:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TenantResponse:
    """Update tenant metadata with optimistic locking.

    Supports updating the organisation name, active status, and full
    configuration (branding, SMTP, languages, retention).  The
    ``version`` field must match the current database version to
    prevent concurrent edit conflicts.

    Requires ``tenants:write`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)

    updated = await tenant_service.update_tenant(
        tenant_id,
        body,
        actor_id=user.id,
    )

    if updated is None:
        # Differentiate not-found from optimistic lock conflict
        existing = await tenant_service.get_tenant_by_id(tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Optimistic locking conflict. The tenant was modified by "
                "another user. Please reload and try again."
            ),
        )

    logger.info(
        "admin_tenant_updated",
        tenant_id=str(tenant_id),
        user_email=user.email,
        changes={
            k: v
            for k, v in body.model_dump(exclude_none=True, exclude={"version"}).items()
            if v is not None
        },
    )

    return TenantResponse.model_validate(updated)


# ── GET /admin/tenants/{tenant_id}/i18n ─────────────────────


@router.get(
    "/{tenant_id}/i18n",
    response_model=I18nConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Get tenant i18n/language configuration",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def get_i18n_config(
    tenant_id: uuid.UUID,
    user=Security(get_current_user, scopes=["tenants:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> I18nConfigResponse:
    """Get the language/i18n configuration for a tenant.

    Returns the list of enabled language codes and the default
    fallback language.

    Requires ``tenants:read`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    config = TenantConfig.model_validate(tenant.config)

    return I18nConfigResponse(
        languages=config.languages,
        default_language=config.default_language,
    )


# ── PUT /admin/tenants/{tenant_id}/i18n ─────────────────────


@router.put(
    "/{tenant_id}/i18n",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Update tenant i18n/language configuration",
    responses={
        404: {"description": "Tenant not found"},
        409: {"description": "Optimistic locking conflict"},
        422: {"description": "Invalid language configuration"},
    },
)
async def update_i18n_config(
    tenant_id: uuid.UUID,
    body: I18nConfigUpdate,
    user=Security(get_current_user, scopes=["tenants:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TenantResponse:
    """Update the language/i18n configuration for a tenant.

    Sets the enabled language codes and default fallback language.
    The default language must be included in the languages list.

    Requires ``tenants:write`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)

    try:
        updated = await tenant_service.update_language_settings(
            tenant_id,
            languages=body.languages,
            default_language=body.default_language,
            expected_version=body.version,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    if updated is None:
        existing = await tenant_service.get_tenant_by_id(tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Optimistic locking conflict. The tenant was modified by "
                "another user. Please reload and try again."
            ),
        )

    logger.info(
        "admin_tenant_i18n_updated",
        tenant_id=str(tenant_id),
        user_email=user.email,
        languages=body.languages,
        default_language=body.default_language,
    )

    return TenantResponse.model_validate(updated)


# ── GET /admin/tenants/{tenant_id}/channels ─────────────────


@router.get(
    "/{tenant_id}/channels",
    response_model=ChannelActivationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get channel activation status",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def get_channel_activation(
    tenant_id: uuid.UUID,
    user=Security(get_current_user, scopes=["tenants:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> ChannelActivationResponse:
    """Get the channel activation status for a tenant.

    Returns whether HinSchG (internal whistleblowing) and LkSG
    (supply chain complaints) channels are enabled.

    Requires ``tenants:read`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    config = tenant.config if isinstance(tenant.config, dict) else {}

    return ChannelActivationResponse(
        hinschg_enabled=config.get("hinschg_enabled", True),
        lksg_enabled=config.get("lksg_enabled", True),
    )


# ── PUT /admin/tenants/{tenant_id}/channels ─────────────────


@router.put(
    "/{tenant_id}/channels",
    response_model=TenantResponse,
    status_code=status.HTTP_200_OK,
    summary="Update channel activation (HinSchG / LkSG)",
    responses={
        404: {"description": "Tenant not found"},
        409: {"description": "Optimistic locking conflict"},
    },
)
async def update_channel_activation(
    tenant_id: uuid.UUID,
    body: ChannelActivationUpdate,
    user=Security(get_current_user, scopes=["tenants:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TenantResponse:
    """Update the channel activation for a tenant.

    Each tenant can independently enable or disable the HinSchG
    (internal whistleblowing) and LkSG (supply chain complaints)
    channels.

    Requires ``tenants:write`` scope (SYSTEM_ADMIN, TENANT_ADMIN).
    """
    tenant_service = TenantService(db)

    updated = await tenant_service.update_channel_activation(
        tenant_id,
        hinschg_enabled=body.hinschg_enabled,
        lksg_enabled=body.lksg_enabled,
        expected_version=body.version,
        actor_id=user.id,
    )

    if updated is None:
        existing = await tenant_service.get_tenant_by_id(tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Optimistic locking conflict. The tenant was modified by "
                "another user. Please reload and try again."
            ),
        )

    logger.info(
        "admin_tenant_channels_updated",
        tenant_id=str(tenant_id),
        user_email=user.email,
        hinschg_enabled=body.hinschg_enabled,
        lksg_enabled=body.lksg_enabled,
    )

    return TenantResponse.model_validate(updated)
