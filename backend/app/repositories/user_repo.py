"""Hinweisgebersystem – User Repository.

Encapsulates database access for the ``User`` model including:
- CRUD operations with RLS tenant scoping
- Lookup by email or OIDC subject claim
- Role management
- Login timestamp tracking
- Listing with pagination

Backend users authenticate via OIDC (Microsoft Entra ID).  This
repository does NOT handle anonymous reporters — those are identified
solely by case number and passphrase hash on the ``Report`` model.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.schemas.common import PaginationMeta, PaginationParams

logger = structlog.get_logger(__name__)


class UserRepository:
    """Data access layer for backend users.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Create ────────────────────────────────────────────────

    async def create(self, user: User) -> User:
        """Insert a new user and return it with generated defaults.

        The caller must populate ``tenant_id``, ``email``,
        ``display_name``, ``oidc_subject``, and ``role``.
        """
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        logger.info(
            "user_created",
            email=user.email,
            role=user.role.value,
        )
        return user

    # ── Read (single) ─────────────────────────────────────────

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Fetch a single user by primary key.

        Returns ``None`` if not found or filtered by RLS.
        """
        stmt = select(User).where(User.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by their email address.

        Email lookup is scoped to the current tenant via RLS.
        """
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_oidc_subject(self, oidc_subject: str) -> User | None:
        """Fetch a user by their OIDC subject claim.

        The ``oidc_subject`` is globally unique (from Microsoft Entra ID)
        but the query still runs within the tenant-scoped RLS session.
        """
        stmt = select(User).where(User.oidc_subject == oidc_subject)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (list) ───────────────────────────────────────────

    async def list_paginated(
        self,
        *,
        pagination: PaginationParams,
        role: UserRole | None = None,
        is_active: bool | None = None,
        is_custodian: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[User], PaginationMeta]:
        """List users with optional filtering and pagination.

        Parameters
        ----------
        pagination:
            Page number and page size.
        role:
            Filter by RBAC role.
        is_active:
            Filter by active/inactive status.
        is_custodian:
            Filter by custodian capability.
        search:
            Case-insensitive search on email and display_name.

        Returns
        -------
        tuple[list[User], PaginationMeta]
            The page of users and pagination metadata.
        """
        stmt = select(User)

        if role is not None:
            stmt = stmt.where(User.role == role)

        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        if is_custodian is not None:
            stmt = stmt.where(User.is_custodian == is_custodian)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                User.email.ilike(pattern) | User.display_name.ilike(pattern)
            )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply sorting and pagination
        stmt = stmt.order_by(User.display_name.asc())
        offset = (pagination.page - 1) * pagination.page_size
        stmt = stmt.offset(offset).limit(pagination.page_size)

        result = await self._session.execute(stmt)
        users = list(result.scalars().all())

        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=max(1, math.ceil(total / pagination.page_size)),
        )

        return users, meta

    async def list_custodians(self) -> list[User]:
        """List all active users who can act as identity custodians.

        Used when creating an identity disclosure request to show
        available custodians for the 4-eyes principle.
        """
        stmt = (
            select(User)
            .where(User.is_custodian.is_(True), User.is_active.is_(True))
            .order_by(User.display_name.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_handlers(self) -> list[User]:
        """List all active users with handler or higher role.

        Used for the case assignment dropdown in the admin UI.
        """
        handler_roles = [
            UserRole.SYSTEM_ADMIN,
            UserRole.TENANT_ADMIN,
            UserRole.HANDLER,
        ]
        stmt = (
            select(User)
            .where(User.role.in_(handler_roles), User.is_active.is_(True))
            .order_by(User.display_name.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Update ────────────────────────────────────────────────

    async def update(
        self,
        user_id: uuid.UUID,
        **fields: Any,
    ) -> User | None:
        """Update user fields.

        Returns the updated user or ``None`` if not found.
        """
        if not fields:
            return await self.get_by_id(user_id)

        update_data = {k: v for k, v in fields.items() if v is not None}

        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**update_data)
            .returning(User.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()

        if row is None:
            return None

        await self._session.flush()
        return await self.get_by_id(user_id)

    async def update_role(
        self,
        user_id: uuid.UUID,
        role: UserRole,
    ) -> User | None:
        """Change a user's RBAC role.

        Convenience method for role management.
        """
        return await self.update(user_id, role=role)

    async def deactivate(self, user_id: uuid.UUID) -> User | None:
        """Deactivate a user (soft delete).

        Deactivated users cannot log in but their data is preserved
        for audit trail integrity.
        """
        user = await self.update(user_id, is_active=False)
        if user is not None:
            logger.info("user_deactivated", user_id=str(user_id))
        return user

    async def activate(self, user_id: uuid.UUID) -> User | None:
        """Re-activate a previously deactivated user."""
        return await self.update(user_id, is_active=True)

    async def update_last_login(self, user_id: uuid.UUID) -> None:
        """Record the current timestamp as the user's last login time.

        Called after successful OIDC authentication.
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=func.now())
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def set_custodian(
        self,
        user_id: uuid.UUID,
        is_custodian: bool,
    ) -> User | None:
        """Toggle a user's custodian status.

        Custodians can approve or reject identity disclosure requests
        as part of the 4-eyes principle.
        """
        return await self.update(user_id, is_custodian=is_custodian)

    # ── Delete ────────────────────────────────────────────────

    async def delete(self, user_id: uuid.UUID) -> bool:
        """Hard-delete a user by ID.

        Prefer ``deactivate()`` in most cases to preserve audit trail
        integrity.  Hard delete is only appropriate during data
        retention cleanup.

        Returns ``True`` if a user was deleted.
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return False

        await self._session.delete(user)
        await self._session.flush()
        logger.info("user_deleted", user_id=str(user_id))
        return True

    # ── Counts ────────────────────────────────────────────────

    async def count(self, *, is_active: bool | None = None) -> int:
        """Count users, optionally filtered by active status."""
        stmt = select(func.count()).select_from(User)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
        result = await self._session.execute(stmt)
        return result.scalar_one()
