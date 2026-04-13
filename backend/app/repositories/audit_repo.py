"""Hinweisgebersystem – Audit Repository (Append-Only).

Encapsulates database access for the ``AuditLog`` model including:
- Append-only inserts (the only write operation permitted)
- Listing with filters (action, actor, resource, date range)
- Pagination for the admin audit log viewer

The underlying ``audit_logs`` table has database-level rules that block
UPDATE and DELETE operations.  This repository only implements INSERT
and SELECT methods — no update or delete methods exist by design.

All queries run within the RLS-scoped session provided by
``get_db()`` so that tenant isolation is enforced at the database
level.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.schemas.common import PaginationMeta, PaginationParams

logger = structlog.get_logger(__name__)


class AuditRepository:
    """Data access layer for the immutable audit trail.

    This repository is intentionally limited to INSERT and SELECT
    operations.  UPDATE and DELETE are blocked at the database level
    to ensure audit trail integrity.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Insert (append-only) ──────────────────────────────────

    async def insert(self, entry: AuditLog) -> AuditLog:
        """Append a new audit log entry.

        The caller is responsible for populating ``tenant_id``,
        ``action``, ``actor_type``, ``resource_type``, and
        ``resource_id``.  Optional fields include ``actor_id``,
        ``details``, ``ip_address``, and ``user_agent``.
        """
        self._session.add(entry)
        await self._session.flush()
        await self._session.refresh(entry)
        logger.debug(
            "audit_entry_created",
            action=entry.action.value,
            resource=f"{entry.resource_type}/{entry.resource_id}",
        )
        return entry

    async def log(
        self,
        *,
        tenant_id: uuid.UUID,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "system",
        details: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Convenience method to create and insert an audit log entry.

        Builds an ``AuditLog`` instance from keyword arguments and
        delegates to ``insert()``.  This is the preferred method for
        service-layer callers.

        Parameters
        ----------
        tenant_id:
            UUID of the tenant context.
        action:
            The audit action type.
        resource_type:
            Type of affected resource (e.g. ``"report"``, ``"user"``).
        resource_id:
            ID of the affected resource (as string).
        actor_id:
            UUID of the acting user (``None`` for anonymous/system).
        actor_type:
            ``"user"``, ``"reporter"``, or ``"system"``.
        details:
            JSONB object with action-specific data.
        ip_address:
            IP address of the actor (``None`` for reporter actions).
        user_agent:
            HTTP User-Agent header.
        """
        entry = AuditLog(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return await self.insert(entry)

    # ── Read (single) ─────────────────────────────────────────

    async def get_by_id(self, entry_id: uuid.UUID) -> AuditLog | None:
        """Fetch a single audit log entry by primary key."""
        stmt = select(AuditLog).where(AuditLog.id == entry_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (list) ───────────────────────────────────────────

    async def list_paginated(
        self,
        *,
        pagination: PaginationParams,
        action: AuditAction | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditLog], PaginationMeta]:
        """List audit log entries with filtering and pagination.

        All filter parameters are optional and combined with ``AND``.
        Results are ordered by ``created_at`` descending (most recent
        first).

        Parameters
        ----------
        pagination:
            Page number and page size.
        action:
            Filter by audit action type.
        actor_id:
            Filter by the acting user's ID.
        actor_type:
            Filter by actor type (``"user"``, ``"reporter"``, ``"system"``).
        resource_type:
            Filter by resource type (e.g. ``"report"``, ``"user"``).
        resource_id:
            Filter by specific resource ID.
        date_from:
            Filter entries created on or after this date.
        date_to:
            Filter entries created on or before this date.

        Returns
        -------
        tuple[list[AuditLog], PaginationMeta]
            The page of entries and pagination metadata.
        """
        stmt = select(AuditLog)
        stmt = self._apply_filters(
            stmt,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=resource_id,
            date_from=date_from,
            date_to=date_to,
        )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply sorting (newest first) and pagination
        stmt = stmt.order_by(AuditLog.created_at.desc())
        offset = (pagination.page - 1) * pagination.page_size
        stmt = stmt.offset(offset).limit(pagination.page_size)

        result = await self._session.execute(stmt)
        entries = list(result.scalars().all())

        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=max(1, math.ceil(total / pagination.page_size)),
        )

        return entries, meta

    async def list_by_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> list[AuditLog]:
        """List all audit entries for a specific resource.

        Returns entries ordered by creation time (oldest first) to
        provide a chronological timeline of events.
        """
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id,
            )
            .order_by(AuditLog.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_actor(
        self,
        actor_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[AuditLog]:
        """List recent audit entries by a specific actor.

        Returns the most recent entries first, limited to ``limit``
        entries.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Counts ────────────────────────────────────────────────

    async def count(
        self,
        *,
        action: AuditAction | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """Count audit entries with optional filters.

        Useful for dashboard KPI cards (e.g. "actions in last 24h").
        """
        stmt = select(func.count()).select_from(AuditLog)

        if action is not None:
            stmt = stmt.where(AuditLog.action == action)

        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)

        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)

        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ── Private helpers ───────────────────────────────────────

    @staticmethod
    def _apply_filters(
        stmt: Select[tuple[AuditLog]],
        *,
        action: AuditAction | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Select[tuple[AuditLog]]:
        """Apply optional WHERE clauses to an audit log query."""
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)

        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)

        if actor_type is not None:
            stmt = stmt.where(AuditLog.actor_type == actor_type)

        if resource_type is not None:
            stmt = stmt.where(AuditLog.resource_type == resource_type)

        if resource_id is not None:
            stmt = stmt.where(AuditLog.resource_id == resource_id)

        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)

        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)

        return stmt
