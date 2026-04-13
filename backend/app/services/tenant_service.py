"""Hinweisgebersystem -- Tenant Business Service.

Orchestrates all tenant lifecycle operations including:
- **CRUD**: creation with DEK generation, updates with optimistic
  locking, activation/deactivation, and deletion.
- **Branding configuration**: logo URL, primary/accent colours per
  tenant for the reporter portal.
- **SMTP configuration**: per-tenant outgoing email settings with
  fallback to the global SMTP config.
- **Language settings**: enabled languages and default language per
  tenant for i18n support.
- **Retention settings**: configurable HinSchG (3y) and LkSG (7y)
  data retention periods.
- **Channel activation**: enable/disable HinSchG and LkSG reporting
  channels independently per tenant.
- **Category management**: per-language category CRUD for report
  classification with translation support.

The service delegates all database access to ``TenantRepository`` and
all audit logging to ``AuditRepository``.  Tenant configuration is
stored in a JSONB column and exposed through structured Pydantic
sub-models (``TenantConfig``, ``TenantBranding``, ``TenantSMTPConfig``).

Unlike user-scoped services, ``TenantService`` does **not** require an
RLS-scoped session because the ``tenants`` table is global.  However,
category translations are tenant-scoped and do use RLS.

Usage::

    from app.services.tenant_service import TenantService

    service = TenantService(session)
    tenant = await service.create_tenant(data)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.category_translation import CategoryTranslation
from app.models.tenant import Tenant
from app.repositories.audit_repo import AuditRepository
from app.repositories.tenant_repo import TenantRepository
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.tenant import (
    TenantBranding,
    TenantConfig,
    TenantCreate,
    TenantPublicInfo,
    TenantSMTPConfig,
    TenantUpdate,
)

logger = structlog.get_logger(__name__)

# ── Default category keys ───────────────────────────────────
# Pre-defined category keys for new tenants.  Labels are provided
# in German and English.

_DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "key": "corruption",
        "translations": {
            "de": {"label": "Korruption und Bestechung", "description": "Bestechung, Vorteilsnahme, Schmiergelder"},
            "en": {"label": "Corruption and Bribery", "description": "Bribery, kickbacks, improper payments"},
        },
    },
    {
        "key": "fraud",
        "translations": {
            "de": {"label": "Betrug", "description": "Finanzbetrug, Bilanzbetrug, Subventionsbetrug"},
            "en": {"label": "Fraud", "description": "Financial fraud, accounting fraud, subsidy fraud"},
        },
    },
    {
        "key": "discrimination",
        "translations": {
            "de": {"label": "Diskriminierung und Belaestigung", "description": "Diskriminierung, sexuelle Belaestigung, Mobbing"},
            "en": {"label": "Discrimination and Harassment", "description": "Discrimination, sexual harassment, bullying"},
        },
    },
    {
        "key": "data_protection",
        "translations": {
            "de": {"label": "Datenschutzverstoesse", "description": "DSGVO-Verstoesse, unerlaubte Datenverarbeitung"},
            "en": {"label": "Data Protection Violations", "description": "GDPR violations, unauthorized data processing"},
        },
    },
    {
        "key": "environmental",
        "translations": {
            "de": {"label": "Umweltverstoesse", "description": "Umweltverschmutzung, illegale Entsorgung"},
            "en": {"label": "Environmental Violations", "description": "Pollution, illegal waste disposal"},
        },
    },
    {
        "key": "health_safety",
        "translations": {
            "de": {"label": "Arbeitsschutzverstoesse", "description": "Verstoesse gegen Arbeitsschutzvorschriften"},
            "en": {"label": "Health and Safety Violations", "description": "Workplace safety violations"},
        },
    },
    {
        "key": "money_laundering",
        "translations": {
            "de": {"label": "Geldwaesche", "description": "Geldwaesche, Terrorismusfinanzierung"},
            "en": {"label": "Money Laundering", "description": "Money laundering, terrorism financing"},
        },
    },
    {
        "key": "competition_law",
        "translations": {
            "de": {"label": "Kartellrechtsverstoesse", "description": "Preisabsprachen, Marktmanipulation"},
            "en": {"label": "Competition Law Violations", "description": "Price fixing, market manipulation"},
        },
    },
    {
        "key": "human_rights",
        "translations": {
            "de": {"label": "Menschenrechtsverletzungen", "description": "Kinderarbeit, Zwangsarbeit, Menschenhandel"},
            "en": {"label": "Human Rights Violations", "description": "Child labor, forced labor, human trafficking"},
        },
    },
    {
        "key": "other",
        "translations": {
            "de": {"label": "Sonstiges", "description": "Andere Verstoesse, die nicht in die obigen Kategorien passen"},
            "en": {"label": "Other", "description": "Other violations not covered by the categories above"},
        },
    },
]


class TenantService:
    """Business logic for multi-tenant management.

    Parameters
    ----------
    session:
        Async database session.  Note: the ``tenants`` table is global
        (no RLS), but category translations are tenant-scoped.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tenant_repo = TenantRepository(session)
        self._audit_repo = AuditRepository(session)

    # ── Create ───────────────────────────────────────────────

    async def create_tenant(
        self,
        data: TenantCreate,
        *,
        dek_ciphertext: str,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Create a new tenant with default configuration.

        The caller must provide the encrypted Data Encryption Key
        (``dek_ciphertext``) generated via envelope encryption with the
        master key.

        Parameters
        ----------
        data:
            Validated tenant creation schema.
        dek_ciphertext:
            Hex-encoded encrypted per-tenant DEK.
        actor_id:
            UUID of the system admin creating the tenant.

        Returns
        -------
        Tenant
            The newly created tenant with generated defaults.

        Raises
        ------
        ValueError
            If the slug is already taken.
        """
        # Check slug uniqueness
        if await self._tenant_repo.slug_exists(data.slug):
            raise ValueError(
                f"Tenant slug '{data.slug}' is already in use."
            )

        # Serialize config to dict for JSONB storage
        config_dict = data.config.model_dump(mode="json")

        tenant = Tenant(
            slug=data.slug,
            name=data.name,
            is_active=True,
            config=config_dict,
            dek_ciphertext=dek_ciphertext,
        )
        tenant = await self._tenant_repo.create(tenant)

        # Create default categories for the tenant
        await self._create_default_categories(
            tenant_id=tenant.id,
            languages=data.config.languages,
        )

        await self._audit_repo.log(
            tenant_id=tenant.id,
            action=AuditAction.TENANT_CREATED,
            resource_type="tenant",
            resource_id=str(tenant.id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "slug": data.slug,
                "name": data.name,
                "languages": data.config.languages,
            },
        )

        logger.info(
            "tenant_created",
            slug=data.slug,
            tenant_id=str(tenant.id),
        )

        return tenant

    # ── Read (single) ────────────────────────────────────────

    async def get_tenant_by_id(
        self,
        tenant_id: uuid.UUID,
    ) -> Tenant | None:
        """Fetch a single tenant by primary key."""
        return await self._tenant_repo.get_by_id(tenant_id)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """Fetch a tenant by its URL-safe slug.

        Used by the tenant resolver middleware.
        """
        return await self._tenant_repo.get_by_slug(slug)

    async def get_active_tenant_by_slug(self, slug: str) -> Tenant | None:
        """Fetch an active tenant by slug.

        Returns ``None`` if the tenant doesn't exist or is inactive.
        """
        return await self._tenant_repo.get_active_by_slug(slug)

    async def get_public_info(self, slug: str) -> TenantPublicInfo | None:
        """Get public-facing tenant information for the reporter portal.

        Returns branding, languages, and display name without exposing
        internal configuration (SMTP, DEK, etc.).

        Parameters
        ----------
        slug:
            Tenant slug for lookup.

        Returns
        -------
        TenantPublicInfo | None
            Public tenant info or ``None`` if not found / inactive.
        """
        tenant = await self._tenant_repo.get_active_by_slug(slug)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)

        return TenantPublicInfo(
            slug=tenant.slug,
            name=tenant.name,
            branding=config.branding,
            languages=config.languages,
            default_language=config.default_language,
        )

    # ── Read (list) ──────────────────────────────────────────

    async def list_tenants(
        self,
        *,
        pagination: PaginationParams,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[Tenant], PaginationMeta]:
        """List tenants with optional filtering and pagination."""
        return await self._tenant_repo.list_paginated(
            pagination=pagination,
            is_active=is_active,
            search=search,
        )

    async def list_all_active_tenants(self) -> list[Tenant]:
        """List all active tenants (no pagination).

        Used by background tasks (deadline checking, data retention).
        """
        return await self._tenant_repo.list_all_active()

    # ── Update ───────────────────────────────────────────────

    async def update_tenant(
        self,
        tenant_id: uuid.UUID,
        data: TenantUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Update tenant fields with optimistic locking.

        Handles name, activation status, and configuration updates.
        All changes are logged to the audit trail.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant to update.
        data:
            Validated update schema (includes ``version`` for optimistic
            locking).
        actor_id:
            UUID of the admin performing the update.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` if not found or on
            optimistic lock conflict.
        """
        update_fields: dict[str, Any] = {}
        audit_details: dict[str, Any] = {}

        if data.name is not None:
            update_fields["name"] = data.name
            audit_details["name"] = data.name

        if data.is_active is not None:
            update_fields["is_active"] = data.is_active
            audit_details["is_active"] = data.is_active

        if data.config is not None:
            config_dict = data.config.model_dump(mode="json")
            update_fields["config"] = config_dict
            audit_details["config_updated"] = True

        if not update_fields:
            return await self._tenant_repo.get_by_id(tenant_id)

        updated = await self._tenant_repo.update(
            tenant_id,
            expected_version=data.version,
            **update_fields,
        )

        if updated is not None:
            # Determine specific audit action
            if "is_active" in update_fields and not update_fields["is_active"]:
                action = AuditAction.TENANT_DEACTIVATED
            else:
                action = AuditAction.TENANT_UPDATED

            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=action,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details=audit_details,
            )

            logger.info(
                "tenant_updated",
                tenant_id=str(tenant_id),
                changes=list(update_fields.keys()),
            )
        else:
            logger.warning(
                "tenant_update_failed",
                tenant_id=str(tenant_id),
                reason="not_found_or_version_conflict",
            )

        return updated

    # ── Branding Configuration ───────────────────────────────

    async def update_branding(
        self,
        tenant_id: uuid.UUID,
        branding: TenantBranding,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Update the tenant's branding configuration.

        Merges the new branding settings into the existing config
        and persists via optimistic locking.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        branding:
            New branding settings (logo URL, colours).
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` on conflict / not found.
        """
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)
        config.branding = branding
        config_dict = config.model_dump(mode="json")

        updated = await self._tenant_repo.update_config(
            tenant_id,
            config_dict,
            expected_version=expected_version,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "config_section": "branding",
                    "branding": branding.model_dump(mode="json"),
                },
            )

        return updated

    # ── SMTP Configuration ───────────────────────────────────

    async def update_smtp_config(
        self,
        tenant_id: uuid.UUID,
        smtp_config: TenantSMTPConfig | None,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Update the tenant's per-tenant SMTP configuration.

        Pass ``None`` to remove the per-tenant SMTP config and fall
        back to the global SMTP settings.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        smtp_config:
            New SMTP settings or ``None`` to clear.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` on conflict / not found.
        """
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)
        config.smtp = smtp_config
        config_dict = config.model_dump(mode="json")

        updated = await self._tenant_repo.update_config(
            tenant_id,
            config_dict,
            expected_version=expected_version,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "config_section": "smtp",
                    "smtp_configured": smtp_config is not None,
                },
            )

        return updated

    # ── Language Settings ────────────────────────────────────

    async def update_language_settings(
        self,
        tenant_id: uuid.UUID,
        *,
        languages: list[str],
        default_language: str,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Update the tenant's language configuration.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        languages:
            List of enabled ISO 639-1 language codes.
        default_language:
            Fallback language code (must be in ``languages``).
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` on conflict / not found.

        Raises
        ------
        ValueError
            If the default language is not in the enabled languages list.
        """
        if default_language not in languages:
            raise ValueError(
                f"Default language '{default_language}' must be included "
                f"in the enabled languages list: {languages}."
            )

        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)
        old_languages = config.languages
        config.languages = languages
        config.default_language = default_language
        config_dict = config.model_dump(mode="json")

        updated = await self._tenant_repo.update_config(
            tenant_id,
            config_dict,
            expected_version=expected_version,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "config_section": "languages",
                    "old_languages": old_languages,
                    "new_languages": languages,
                    "default_language": default_language,
                },
            )

        return updated

    # ── Retention Settings ───────────────────────────────────

    async def update_retention_settings(
        self,
        tenant_id: uuid.UUID,
        *,
        retention_hinschg_years: int | None = None,
        retention_lksg_years: int | None = None,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Update the tenant's data retention periods.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        retention_hinschg_years:
            Retention period for HinSchG reports (default: 3 years).
        retention_lksg_years:
            Retention period for LkSG reports (default: 7 years).
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` on conflict / not found.
        """
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)

        if retention_hinschg_years is not None:
            config.retention_hinschg_years = retention_hinschg_years

        if retention_lksg_years is not None:
            config.retention_lksg_years = retention_lksg_years

        config_dict = config.model_dump(mode="json")

        updated = await self._tenant_repo.update_config(
            tenant_id,
            config_dict,
            expected_version=expected_version,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "config_section": "retention",
                    "retention_hinschg_years": config.retention_hinschg_years,
                    "retention_lksg_years": config.retention_lksg_years,
                },
            )

        return updated

    # ── Channel Activation ───────────────────────────────────

    async def update_channel_activation(
        self,
        tenant_id: uuid.UUID,
        *,
        hinschg_enabled: bool | None = None,
        lksg_enabled: bool | None = None,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Enable or disable reporting channels for a tenant.

        Each tenant can independently activate the HinSchG (internal
        whistleblowing) and LkSG (supply chain complaints) channels.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        hinschg_enabled:
            Whether the HinSchG channel is enabled.
        lksg_enabled:
            Whether the LkSG channel is enabled.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        Tenant | None
            The updated tenant or ``None`` on conflict / not found.
        """
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return None

        config = TenantConfig.model_validate(tenant.config)
        config_dict = config.model_dump(mode="json")

        # Store channel activation in the config JSONB
        if hinschg_enabled is not None:
            config_dict["hinschg_enabled"] = hinschg_enabled

        if lksg_enabled is not None:
            config_dict["lksg_enabled"] = lksg_enabled

        updated = await self._tenant_repo.update_config(
            tenant_id,
            config_dict,
            expected_version=expected_version,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "config_section": "channels",
                    "hinschg_enabled": config_dict.get("hinschg_enabled"),
                    "lksg_enabled": config_dict.get("lksg_enabled"),
                },
            )

        return updated

    # ── Activation / Deactivation ────────────────────────────

    async def activate_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Re-activate a deactivated tenant.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the action.

        Returns
        -------
        Tenant | None
            The activated tenant or ``None`` on conflict / not found.
        """
        activated = await self._tenant_repo.activate(
            tenant_id,
            expected_version=expected_version,
        )

        if activated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_UPDATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={"is_active": True},
            )

            logger.info(
                "tenant_activated",
                tenant_id=str(tenant_id),
            )

        return activated

    async def deactivate_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant | None:
        """Deactivate a tenant (soft disable).

        Inactive tenants return 403 on all endpoints.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the admin performing the action.

        Returns
        -------
        Tenant | None
            The deactivated tenant or ``None`` on conflict / not found.
        """
        deactivated = await self._tenant_repo.deactivate(
            tenant_id,
            expected_version=expected_version,
        )

        if deactivated is not None:
            await self._audit_repo.log(
                tenant_id=tenant_id,
                action=AuditAction.TENANT_DEACTIVATED,
                resource_type="tenant",
                resource_id=str(tenant_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={"is_active": False},
            )

            logger.info(
                "tenant_deactivated",
                tenant_id=str(tenant_id),
            )

        return deactivated

    # ── Delete ───────────────────────────────────────────────

    async def delete_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> bool:
        """Hard-delete a tenant and all associated data.

        This is a destructive operation.  All reports, messages,
        attachments, users, categories, and audit logs for this tenant
        will be permanently deleted via cascade.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant to delete.
        actor_id:
            UUID of the system admin performing the deletion.

        Returns
        -------
        bool
            ``True`` if the tenant was deleted.
        """
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            return False

        # Audit before deletion (tenant data will be gone after)
        await self._audit_repo.log(
            tenant_id=tenant_id,
            action=AuditAction.TENANT_DEACTIVATED,
            resource_type="tenant",
            resource_id=str(tenant_id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "slug": tenant.slug,
                "name": tenant.name,
                "action": "hard_delete",
            },
        )

        deleted = await self._tenant_repo.delete(tenant_id)

        if deleted:
            logger.info(
                "tenant_deleted",
                tenant_id=str(tenant_id),
                slug=tenant.slug,
            )

        return deleted

    # ── Category Management ──────────────────────────────────

    async def list_categories(
        self,
        tenant_id: uuid.UUID,
        *,
        language: str | None = None,
        active_only: bool = True,
    ) -> list[CategoryTranslation]:
        """List categories for a tenant, optionally filtered by language.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        language:
            ISO 639-1 language code to filter by.  If ``None``, returns
            categories for all languages.
        active_only:
            If ``True`` (default), only return active categories.

        Returns
        -------
        list[CategoryTranslation]
            Category translations sorted by sort order.
        """
        stmt = (
            select(CategoryTranslation)
            .where(CategoryTranslation.tenant_id == tenant_id)
        )

        if language is not None:
            stmt = stmt.where(CategoryTranslation.language == language)

        if active_only:
            stmt = stmt.where(CategoryTranslation.is_active.is_(True))

        stmt = stmt.order_by(
            CategoryTranslation.sort_order.asc(),
            CategoryTranslation.category_key.asc(),
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_category(
        self,
        tenant_id: uuid.UUID,
        *,
        category_key: str,
        language: str,
        label: str,
        description: str | None = None,
        sort_order: int = 0,
        actor_id: uuid.UUID | None = None,
    ) -> CategoryTranslation:
        """Create a new category translation for a tenant.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        category_key:
            Machine-readable category identifier.
        language:
            ISO 639-1 language code.
        label:
            Human-readable translated category name.
        description:
            Optional help text for the category.
        sort_order:
            Display order (ascending).
        actor_id:
            UUID of the admin creating the category.

        Returns
        -------
        CategoryTranslation
            The newly created category translation.
        """
        category = CategoryTranslation(
            tenant_id=tenant_id,
            category_key=category_key,
            language=language,
            label=label,
            description=description,
            sort_order=sort_order,
            is_active=True,
        )

        self._session.add(category)
        await self._session.flush()
        await self._session.refresh(category)

        await self._audit_repo.log(
            tenant_id=tenant_id,
            action=AuditAction.CATEGORY_CREATED,
            resource_type="category",
            resource_id=str(category.id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "category_key": category_key,
                "language": language,
                "label": label,
            },
        )

        logger.info(
            "category_created",
            tenant_id=str(tenant_id),
            category_key=category_key,
            language=language,
        )

        return category

    async def update_category(
        self,
        category_id: uuid.UUID,
        *,
        label: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
        is_active: bool | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> CategoryTranslation | None:
        """Update a category translation.

        Parameters
        ----------
        category_id:
            UUID of the category translation to update.
        label:
            Updated translated label.
        description:
            Updated help text.
        sort_order:
            Updated display order.
        is_active:
            Activate or deactivate the category.
        actor_id:
            UUID of the admin performing the update.

        Returns
        -------
        CategoryTranslation | None
            The updated category or ``None`` if not found.
        """
        stmt = select(CategoryTranslation).where(
            CategoryTranslation.id == category_id,
        )
        result = await self._session.execute(stmt)
        category = result.scalar_one_or_none()

        if category is None:
            return None

        audit_details: dict[str, Any] = {
            "category_key": category.category_key,
            "language": category.language,
        }

        if label is not None:
            category.label = label
            audit_details["label"] = label

        if description is not None:
            category.description = description

        if sort_order is not None:
            category.sort_order = sort_order

        if is_active is not None:
            category.is_active = is_active
            audit_details["is_active"] = is_active

        await self._session.flush()
        await self._session.refresh(category)

        await self._audit_repo.log(
            tenant_id=category.tenant_id,
            action=AuditAction.CATEGORY_UPDATED,
            resource_type="category",
            resource_id=str(category_id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details=audit_details,
        )

        logger.info(
            "category_updated",
            category_id=str(category_id),
            category_key=category.category_key,
        )

        return category

    async def delete_category(
        self,
        category_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> bool:
        """Delete a category translation.

        Prefer deactivating categories (``is_active=False``) to preserve
        existing report references.  Hard delete is only appropriate
        when the category was created in error.

        Parameters
        ----------
        category_id:
            UUID of the category translation to delete.
        actor_id:
            UUID of the admin performing the deletion.

        Returns
        -------
        bool
            ``True`` if the category was deleted.
        """
        stmt = select(CategoryTranslation).where(
            CategoryTranslation.id == category_id,
        )
        result = await self._session.execute(stmt)
        category = result.scalar_one_or_none()

        if category is None:
            return False

        await self._audit_repo.log(
            tenant_id=category.tenant_id,
            action=AuditAction.CATEGORY_DELETED,
            resource_type="category",
            resource_id=str(category_id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "category_key": category.category_key,
                "language": category.language,
                "label": category.label,
            },
        )

        await self._session.delete(category)
        await self._session.flush()

        logger.info(
            "category_deleted",
            category_id=str(category_id),
            category_key=category.category_key,
        )

        return True

    async def create_category_translations(
        self,
        tenant_id: uuid.UUID,
        *,
        category_key: str,
        translations: dict[str, dict[str, str]],
        sort_order: int = 0,
        actor_id: uuid.UUID | None = None,
    ) -> list[CategoryTranslation]:
        """Create a category with translations for multiple languages.

        Convenience method for creating a category key with all its
        language translations at once.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant.
        category_key:
            Machine-readable category identifier.
        translations:
            Dict mapping language codes to dicts with ``label`` and
            optional ``description`` keys.
        sort_order:
            Display order (ascending).
        actor_id:
            UUID of the admin creating the category.

        Returns
        -------
        list[CategoryTranslation]
            List of created category translations.
        """
        categories: list[CategoryTranslation] = []

        for language, content in translations.items():
            category = await self.create_category(
                tenant_id,
                category_key=category_key,
                language=language,
                label=content["label"],
                description=content.get("description"),
                sort_order=sort_order,
                actor_id=actor_id,
            )
            categories.append(category)

        return categories

    # ── Counts ──────────────────────────────────────────────

    async def count_tenants(
        self,
        *,
        is_active: bool | None = None,
    ) -> int:
        """Count tenants, optionally filtered by active status."""
        return await self._tenant_repo.count(is_active=is_active)

    # ── Private helpers ─────────────────────────────────────

    async def _create_default_categories(
        self,
        tenant_id: uuid.UUID,
        languages: list[str],
    ) -> None:
        """Seed the default categories for a newly created tenant.

        Creates translations for each default category in all of the
        tenant's enabled languages.

        Parameters
        ----------
        tenant_id:
            UUID of the new tenant.
        languages:
            List of enabled language codes for this tenant.
        """
        for sort_order, cat_def in enumerate(_DEFAULT_CATEGORIES):
            for language in languages:
                translations = cat_def["translations"]
                # Fall back to English if the language is not in the
                # default translations, then to German.
                content = translations.get(
                    language,
                    translations.get("en", translations.get("de", {})),
                )

                category = CategoryTranslation(
                    tenant_id=tenant_id,
                    category_key=cat_def["key"],
                    language=language,
                    label=content.get("label", cat_def["key"]),
                    description=content.get("description"),
                    sort_order=sort_order,
                    is_active=True,
                )
                self._session.add(category)

        await self._session.flush()

        logger.info(
            "default_categories_created",
            tenant_id=str(tenant_id),
            category_count=len(_DEFAULT_CATEGORIES),
            languages=languages,
        )
