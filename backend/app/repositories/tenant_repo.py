"""Hinweisgebersystem – Tenant Repository.

Encapsulates database access for the ``Tenant`` model including:
- CRUD operations (tenants are NOT scoped by RLS — they are global)
- Lookup by slug (for tenant resolution middleware)
- Configuration management (JSONB config updates)
- Optimistic locking on updates via ``version`` column

Unlike other repositories, TenantRepository queries are **not** scoped
by RLS because the ``tenants`` table has no ``tenant_id`` column and no
RLS policies.  The tenant resolver middleware needs to look up tenants
before a tenant context is established.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.common import PaginationMeta, PaginationParams

logger = structlog.get_logger(__name__)


class TenantRepository:
    """Data access layer for tenants (organisations).

    Parameters
    ----------
    session:
        Async database session.  Note: RLS does not apply to the
        ``tenants`` table so no tenant context is required.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Create ────────────────────────────────────────────────

    async def create(self, tenant: Tenant) -> Tenant:
        """Insert a new tenant and return it with generated defaults.

        The caller must populate ``slug``, ``name``, and
        ``dek_ciphertext`` (encrypted Data Encryption Key).
        """
        self._session.add(tenant)
        await self._session.flush()
        await self._session.refresh(tenant)
        logger.info("tenant_created", slug=tenant.slug)
        return tenant

    # ── Read (single) ─────────────────────────────────────────

    async def get_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        """Fetch a single tenant by primary key."""
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Fetch a tenant by its URL-safe slug.

        This is the primary lookup method used by the tenant resolver
        middleware to map a subdomain or URL path prefix to a tenant.
        """
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_slug(self, slug: str) -> Tenant | None:
        """Fetch an active tenant by slug.

        Returns ``None`` if the tenant doesn't exist or is inactive.
        Inactive tenants should receive a 403 response.
        """
        stmt = select(Tenant).where(
            Tenant.slug == slug,
            Tenant.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (list) ───────────────────────────────────────────

    async def list_paginated(
        self,
        *,
        pagination: PaginationParams,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[Tenant], PaginationMeta]:
        """List tenants with optional filtering and pagination.

        Parameters
        ----------
        pagination:
            Page number and page size.
        is_active:
            Filter by active/inactive status.
        search:
            Case-insensitive search on slug and name.

        Returns
        -------
        tuple[list[Tenant], PaginationMeta]
            The page of tenants and pagination metadata.
        """
        stmt = select(Tenant)

        if is_active is not None:
            stmt = stmt.where(Tenant.is_active == is_active)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                Tenant.slug.ilike(pattern) | Tenant.name.ilike(pattern)
            )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply sorting and pagination
        stmt = stmt.order_by(Tenant.name.asc())
        offset = (pagination.page - 1) * pagination.page_size
        stmt = stmt.offset(offset).limit(pagination.page_size)

        result = await self._session.execute(stmt)
        tenants = list(result.scalars().all())

        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=max(1, math.ceil(total / pagination.page_size)),
        )

        return tenants, meta

    async def list_all_active(self) -> list[Tenant]:
        """List all active tenants (no pagination).

        Used by background tasks that need to iterate over all tenants
        (e.g. deadline checking, data retention).
        """
        stmt = (
            select(Tenant)
            .where(Tenant.is_active.is_(True))
            .order_by(Tenant.name.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Update ────────────────────────────────────────────────

    async def update(
        self,
        tenant_id: uuid.UUID,
        *,
        expected_version: int,
        **fields: Any,
    ) -> Tenant | None:
        """Update tenant fields with optimistic locking.

        The ``expected_version`` must match the current database version.
        On success the version is incremented.  Returns ``None`` if the
        tenant is not found or the version has changed (optimistic lock
        conflict).

        Parameters
        ----------
        tenant_id:
            UUID of the tenant to update.
        expected_version:
            The version the caller believes is current.
        **fields:
            Column names and their new values.
        """
        if not fields:
            return await self.get_by_id(tenant_id)

        update_data = {k: v for k, v in fields.items() if v is not None}
        update_data["version"] = expected_version + 1
        update_data["updated_at"] = func.now()

        stmt = (
            update(Tenant)
            .where(Tenant.id == tenant_id, Tenant.version == expected_version)
            .values(**update_data)
            .returning(Tenant.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()

        if row is None:
            logger.warning(
                "tenant_update_conflict",
                tenant_id=str(tenant_id),
                expected_version=expected_version,
            )
            return None

        await self._session.flush()
        return await self.get_by_id(tenant_id)

    async def update_config(
        self,
        tenant_id: uuid.UUID,
        config: dict[str, Any],
        *,
        expected_version: int,
    ) -> Tenant | None:
        """Update the tenant's JSONB configuration.

        This replaces the entire ``config`` column.  For partial config
        updates the service layer should merge the new values with the
        existing config before calling this method.
        """
        return await self.update(
            tenant_id,
            expected_version=expected_version,
            config=config,
        )

    async def deactivate(
        self,
        tenant_id: uuid.UUID,
        *,
        expected_version: int,
    ) -> Tenant | None:
        """Deactivate a tenant (soft delete).

        Inactive tenants return 403 on all endpoints.
        """
        tenant = await self.update(
            tenant_id,
            expected_version=expected_version,
            is_active=False,
        )
        if tenant is not None:
            logger.info("tenant_deactivated", tenant_id=str(tenant_id))
        return tenant

    async def activate(
        self,
        tenant_id: uuid.UUID,
        *,
        expected_version: int,
    ) -> Tenant | None:
        """Re-activate a previously deactivated tenant."""
        return await self.update(
            tenant_id,
            expected_version=expected_version,
            is_active=True,
        )

    # ── Delete ────────────────────────────────────────────────

    async def delete(self, tenant_id: uuid.UUID) -> bool:
        """Hard-delete a tenant and cascade to all related data.

        This is a destructive operation — all reports, messages,
        attachments, users, and audit logs for this tenant will be
        permanently deleted.

        Returns ``True`` if a tenant was deleted.
        """
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            return False

        await self._session.delete(tenant)
        await self._session.flush()
        logger.info("tenant_deleted", tenant_id=str(tenant_id))
        return True

    # ── Counts ────────────────────────────────────────────────

    async def count(self, *, is_active: bool | None = None) -> int:
        """Count tenants, optionally filtered by active status."""
        stmt = select(func.count()).select_from(Tenant)
        if is_active is not None:
            stmt = stmt.where(Tenant.is_active == is_active)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def slug_exists(self, slug: str) -> bool:
        """Check if a slug is already taken.

        Used during tenant creation to validate uniqueness before
        hitting a database constraint violation.
        """
        stmt = select(func.count()).select_from(Tenant).where(
            Tenant.slug == slug,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() > 0
