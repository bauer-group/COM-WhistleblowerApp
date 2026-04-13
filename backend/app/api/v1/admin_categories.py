"""Hinweisgebersystem – Admin Category Management API Endpoints.

Provides:
- **GET /admin/tenants/{tenant_id}/categories/{lang}** — List
  categories for a tenant in a specific language.
- **POST /admin/tenants/{tenant_id}/categories/{lang}** — Create
  a new category translation for a tenant and language.
- **GET /admin/tenants/{tenant_id}/categories/{lang}/{category_id}**
  — Get a single category translation by ID.
- **PUT /admin/tenants/{tenant_id}/categories/{lang}/{category_id}**
  — Update a category translation (label, description, sort order,
  active status).
- **GET /admin/tenants/{tenant_id}/email-templates/{lang}** — Get
  email templates for a tenant in a specific language.
- **PUT /admin/tenants/{tenant_id}/email-templates/{lang}** — Update
  email templates for a tenant and language.

Categories are per-tenant, per-language translations for report
classification.  Each category is identified by a stable machine-
readable ``category_key`` (e.g. ``"corruption"``) and has a human-
readable translated label and optional description.

All endpoints require OIDC-authenticated admin users with appropriate
scopes.

Usage::

    from app.api.v1.admin_categories import router as admin_categories_router
    api_v1_router.include_router(admin_categories_router)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_tenant_db
from app.services.tenant_service import TenantService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin-categories"])


# ── Response / Request schemas ──────────────────────────────
# Inline schemas for category and email template endpoints.


class CategoryResponse(BaseModel):
    """Category translation response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    category_key: str
    language: str
    label: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    """Request body for creating a new category translation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category_key: str = Field(
        min_length=1,
        max_length=100,
        description="Machine-readable category identifier (e.g. 'corruption').",
    )
    label: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable translated category name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional help text for the category.",
    )
    sort_order: int = Field(
        default=0,
        ge=0,
        description="Display order (ascending).",
    )


class CategoryUpdate(BaseModel):
    """Request body for updating a category translation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated translated category name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Updated help text.",
    )
    sort_order: int | None = Field(
        default=None,
        ge=0,
        description="Updated display order.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the category.",
    )


class EmailTemplateResponse(BaseModel):
    """Email template configuration for a tenant and language."""

    model_config = ConfigDict(frozen=True)

    language: str = Field(description="ISO 639-1 language code.")
    confirmation_subject: str = Field(
        default="",
        description="Subject line for the report confirmation email.",
    )
    confirmation_body: str = Field(
        default="",
        description="Body template for the report confirmation email.",
    )
    feedback_subject: str = Field(
        default="",
        description="Subject line for the feedback notification email.",
    )
    feedback_body: str = Field(
        default="",
        description="Body template for the feedback notification email.",
    )
    magic_link_subject: str = Field(
        default="",
        description="Subject line for the magic link email.",
    )
    magic_link_body: str = Field(
        default="",
        description="Body template for the magic link email.",
    )


class EmailTemplateUpdate(BaseModel):
    """Request body for updating email templates for a language."""

    model_config = ConfigDict(str_strip_whitespace=True)

    confirmation_subject: str | None = Field(
        default=None,
        max_length=255,
        description="Subject line for the report confirmation email.",
    )
    confirmation_body: str | None = Field(
        default=None,
        max_length=5000,
        description="Body template for the report confirmation email.",
    )
    feedback_subject: str | None = Field(
        default=None,
        max_length=255,
        description="Subject line for the feedback notification email.",
    )
    feedback_body: str | None = Field(
        default=None,
        max_length=5000,
        description="Body template for the feedback notification email.",
    )
    magic_link_subject: str | None = Field(
        default=None,
        max_length=255,
        description="Subject line for the magic link email.",
    )
    magic_link_body: str | None = Field(
        default=None,
        max_length=5000,
        description="Body template for the magic link email.",
    )
    version: int = Field(
        description="Current version for optimistic locking (must match DB).",
    )


# ── GET /admin/tenants/{tenant_id}/categories/{lang} ────────


@router.get(
    "/{tenant_id}/categories/{lang}",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List categories for a tenant in a specific language",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def list_categories(
    tenant_id: uuid.UUID,
    lang: str,
    user=Security(get_current_user, scopes=["categories:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    active_only: bool = Query(
        default=False,
        description="If true, only return active categories.",
    ),
) -> list[CategoryResponse]:
    """List category translations for a tenant and language.

    Returns all categories (or only active ones) sorted by sort order
    for the specified language.

    Requires ``categories:read`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    tenant_service = TenantService(db)

    # Verify the tenant exists
    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    categories = await tenant_service.list_categories(
        tenant_id,
        language=lang,
        active_only=active_only,
    )

    logger.info(
        "admin_categories_listed",
        tenant_id=str(tenant_id),
        language=lang,
        count=len(categories),
        user_email=user.email,
    )

    return [CategoryResponse.model_validate(c) for c in categories]


# ── POST /admin/tenants/{tenant_id}/categories/{lang} ───────


@router.post(
    "/{tenant_id}/categories/{lang}",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new category translation",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def create_category(
    tenant_id: uuid.UUID,
    lang: str,
    body: CategoryCreate,
    user=Security(get_current_user, scopes=["categories:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> CategoryResponse:
    """Create a new category translation for a tenant and language.

    The ``category_key`` is the machine-readable identifier shared
    across languages (e.g. ``"corruption"``).  The ``label`` is the
    human-readable translated name displayed to reporters.

    Requires ``categories:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    tenant_service = TenantService(db)

    # Verify the tenant exists
    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    category = await tenant_service.create_category(
        tenant_id,
        category_key=body.category_key,
        language=lang,
        label=body.label,
        description=body.description,
        sort_order=body.sort_order,
        actor_id=user.id,
    )

    logger.info(
        "admin_category_created",
        tenant_id=str(tenant_id),
        language=lang,
        category_key=body.category_key,
        user_email=user.email,
    )

    return CategoryResponse.model_validate(category)


# ── GET /admin/tenants/{tenant_id}/categories/{lang}/{category_id}


@router.get(
    "/{tenant_id}/categories/{lang}/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single category translation",
    responses={
        404: {"description": "Category not found"},
    },
)
async def get_category(
    tenant_id: uuid.UUID,
    lang: str,
    category_id: uuid.UUID,
    user=Security(get_current_user, scopes=["categories:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> CategoryResponse:
    """Get a single category translation by ID.

    Requires ``categories:read`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    from sqlalchemy import select

    from app.models.category_translation import CategoryTranslation

    stmt = select(CategoryTranslation).where(
        CategoryTranslation.id == category_id,
        CategoryTranslation.tenant_id == tenant_id,
        CategoryTranslation.language == lang,
    )
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found.",
        )

    return CategoryResponse.model_validate(category)


# ── PUT /admin/tenants/{tenant_id}/categories/{lang}/{category_id}


@router.put(
    "/{tenant_id}/categories/{lang}/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a category translation",
    responses={
        404: {"description": "Category not found"},
    },
)
async def update_category(
    tenant_id: uuid.UUID,
    lang: str,
    category_id: uuid.UUID,
    body: CategoryUpdate,
    user=Security(get_current_user, scopes=["categories:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> CategoryResponse:
    """Update a category translation's label, description, sort order,
    or active status.

    All fields are optional — only provided fields will be updated.

    Requires ``categories:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    tenant_service = TenantService(db)

    updated = await tenant_service.update_category(
        category_id,
        label=body.label,
        description=body.description,
        sort_order=body.sort_order,
        is_active=body.is_active,
        actor_id=user.id,
    )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found.",
        )

    logger.info(
        "admin_category_updated",
        tenant_id=str(tenant_id),
        language=lang,
        category_id=str(category_id),
        user_email=user.email,
    )

    return CategoryResponse.model_validate(updated)


# ── GET /admin/tenants/{tenant_id}/email-templates/{lang} ───


@router.get(
    "/{tenant_id}/email-templates/{lang}",
    response_model=EmailTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get email templates for a tenant and language",
    responses={
        404: {"description": "Tenant not found"},
    },
)
async def get_email_templates(
    tenant_id: uuid.UUID,
    lang: str,
    user=Security(get_current_user, scopes=["tenants:read"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> EmailTemplateResponse:
    """Get the email templates for a tenant in a specific language.

    Email templates are stored in the tenant's JSONB config under
    ``email_templates.{lang}``.  Returns default empty strings if
    no templates are configured.

    Requires ``tenants:read`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    tenant_service = TenantService(db)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    config = tenant.config if isinstance(tenant.config, dict) else {}
    email_templates = config.get("email_templates", {})
    lang_templates = email_templates.get(lang, {})

    return EmailTemplateResponse(
        language=lang,
        confirmation_subject=lang_templates.get("confirmation_subject", ""),
        confirmation_body=lang_templates.get("confirmation_body", ""),
        feedback_subject=lang_templates.get("feedback_subject", ""),
        feedback_body=lang_templates.get("feedback_body", ""),
        magic_link_subject=lang_templates.get("magic_link_subject", ""),
        magic_link_body=lang_templates.get("magic_link_body", ""),
    )


# ── PUT /admin/tenants/{tenant_id}/email-templates/{lang} ───


@router.put(
    "/{tenant_id}/email-templates/{lang}",
    response_model=EmailTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update email templates for a tenant and language",
    responses={
        404: {"description": "Tenant not found"},
        409: {"description": "Optimistic locking conflict"},
    },
)
async def update_email_templates(
    tenant_id: uuid.UUID,
    lang: str,
    body: EmailTemplateUpdate,
    user=Security(get_current_user, scopes=["tenants:write"]),
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> EmailTemplateResponse:
    """Update the email templates for a tenant in a specific language.

    Templates support placeholders like ``{case_number}``,
    ``{magic_link_url}``, etc., which are resolved at send time.
    Only provided fields will be updated — omitted fields retain
    their current values.

    Requires ``tenants:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    from app.models.audit_log import AuditAction
    from app.repositories.audit_repo import AuditRepository
    from app.repositories.tenant_repo import TenantRepository

    tenant_repo = TenantRepository(db)
    audit_repo = AuditRepository(db)

    tenant = await tenant_repo.get_by_id(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    # Merge templates into the existing config
    config = dict(tenant.config) if isinstance(tenant.config, dict) else {}
    email_templates = config.get("email_templates", {})
    lang_templates = dict(email_templates.get(lang, {}))

    # Update only provided fields
    update_fields = body.model_dump(exclude_none=True, exclude={"version"})
    for key, value in update_fields.items():
        lang_templates[key] = value

    email_templates[lang] = lang_templates
    config["email_templates"] = email_templates

    # Persist with optimistic locking
    updated = await tenant_repo.update_config(
        tenant_id,
        config,
        expected_version=body.version,
    )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Optimistic locking conflict. The tenant was modified by "
                "another user. Please reload and try again."
            ),
        )

    # Audit trail
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.TENANT_UPDATED,
        resource_type="tenant",
        resource_id=str(tenant_id),
        actor_id=user.id,
        actor_type="user",
        details={
            "config_section": "email_templates",
            "language": lang,
            "updated_fields": list(update_fields.keys()),
        },
    )

    logger.info(
        "admin_email_templates_updated",
        tenant_id=str(tenant_id),
        language=lang,
        user_email=user.email,
        updated_fields=list(update_fields.keys()),
    )

    # Return the merged templates
    return EmailTemplateResponse(
        language=lang,
        confirmation_subject=lang_templates.get("confirmation_subject", ""),
        confirmation_body=lang_templates.get("confirmation_body", ""),
        feedback_subject=lang_templates.get("feedback_subject", ""),
        feedback_body=lang_templates.get("feedback_body", ""),
        magic_link_subject=lang_templates.get("magic_link_subject", ""),
        magic_link_body=lang_templates.get("magic_link_body", ""),
    )
