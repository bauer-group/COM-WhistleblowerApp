"""Hinweisgebersystem – Report Repository.

Encapsulates all database access for the ``Report`` model including:
- CRUD operations respecting RLS (tenant context set in session)
- Full-text search via PostgreSQL ``tsvector`` / ``to_tsquery``
- Pagination with configurable page size
- Filtering by status, category, date range, priority, channel,
  assigned handler, and overdue deadlines
- Optimistic locking on updates via ``version`` column

All queries run within the RLS-scoped session provided by
``get_db()`` so that tenant isolation is enforced at the database
level — the repository does not manually filter by ``tenant_id``.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import Select, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.report import (
    Channel,
    Priority,
    Report,
    ReportStatus,
)
from app.schemas.common import PaginationMeta, PaginationParams

logger = structlog.get_logger(__name__)


class ReportRepository:
    """Data access layer for whistleblower reports.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Create ────────────────────────────────────────────────

    async def create(self, report: Report) -> Report:
        """Insert a new report and return it with generated defaults.

        The caller is responsible for populating all required fields
        including ``tenant_id``, ``case_number``, and ``passphrase_hash``.
        """
        self._session.add(report)
        await self._session.flush()
        await self._session.refresh(report)
        logger.info(
            "report_created",
            case_number=report.case_number,
            channel=report.channel.value,
        )
        return report

    # ── Read (single) ─────────────────────────────────────────

    async def get_by_id(
        self,
        report_id: uuid.UUID,
        *,
        with_messages: bool = False,
        with_attachments: bool = False,
    ) -> Report | None:
        """Fetch a single report by primary key.

        RLS ensures only reports belonging to the current tenant are
        visible.  Returns ``None`` if not found (or filtered by RLS).

        Parameters
        ----------
        report_id:
            UUID of the report.
        with_messages:
            Eagerly load the messages relationship.
        with_attachments:
            Eagerly load the attachments relationship.
        """
        stmt = select(Report).where(Report.id == report_id)
        stmt = self._apply_eager_loading(stmt, with_messages, with_attachments)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_case_number(
        self,
        case_number: str,
        *,
        with_messages: bool = False,
        with_attachments: bool = False,
    ) -> Report | None:
        """Fetch a single report by its public case number.

        This is the primary lookup method for the reporter mailbox.
        The case number is unique across all tenants but RLS still
        filters by the current tenant context.
        """
        stmt = select(Report).where(Report.case_number == case_number)
        stmt = self._apply_eager_loading(stmt, with_messages, with_attachments)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (list) ───────────────────────────────────────────

    async def list_paginated(
        self,
        *,
        pagination: PaginationParams,
        status: ReportStatus | None = None,
        priority: Priority | None = None,
        channel: Channel | None = None,
        category: str | None = None,
        assigned_to: uuid.UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        overdue_only: bool = False,
        sort_by: str = "created_at",
        sort_desc: bool = True,
    ) -> tuple[list[Report], PaginationMeta]:
        """List reports with filtering, search, and pagination.

        All filter parameters are optional and combined with ``AND``.
        Full-text search uses PostgreSQL ``to_tsquery('german', ...)``
        against the ``search_vector`` tsvector column.

        Returns
        -------
        tuple[list[Report], PaginationMeta]
            The page of reports and pagination metadata.
        """
        # Build base query
        stmt = select(Report)
        stmt = self._apply_filters(
            stmt,
            status=status,
            priority=priority,
            channel=channel,
            category=category,
            assigned_to=assigned_to,
            search=search,
            date_from=date_from,
            date_to=date_to,
            overdue_only=overdue_only,
        )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # Apply sorting
        sort_column = self._resolve_sort_column(sort_by)
        if sort_desc:
            stmt = stmt.order_by(sort_column.desc())
        else:
            stmt = stmt.order_by(sort_column.asc())

        # Apply pagination
        offset = (pagination.page - 1) * pagination.page_size
        stmt = stmt.offset(offset).limit(pagination.page_size)

        result = await self._session.execute(stmt)
        reports = list(result.scalars().all())

        meta = PaginationMeta(
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
            total_pages=max(1, math.ceil(total / pagination.page_size)),
        )

        return reports, meta

    async def count_by_status(self) -> dict[str, int]:
        """Return a count of reports grouped by status.

        Useful for the admin dashboard KPI cards.
        """
        stmt = (
            select(Report.status, func.count())
            .group_by(Report.status)
        )
        result = await self._session.execute(stmt)
        return {row[0].value: row[1] for row in result.all()}

    async def get_overdue_reports(self) -> list[Report]:
        """Fetch reports with overdue deadlines.

        A report is overdue if:
        - ``confirmation_deadline`` has passed and ``confirmation_sent_at``
          is still ``None``, or
        - ``feedback_deadline`` has passed and ``feedback_sent_at``
          is still ``None``.
        """
        now = func.now()
        stmt = select(Report).where(
            (
                (Report.confirmation_deadline < now)
                & (Report.confirmation_sent_at.is_(None))
            )
            | (
                (Report.feedback_deadline < now)
                & (Report.feedback_sent_at.is_(None))
            )
        )
        stmt = stmt.order_by(Report.created_at.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_reports(self) -> list[Report]:
        """Fetch reports past their retention date for auto-deletion."""
        stmt = select(Report).where(
            Report.retention_until.isnot(None),
            Report.retention_until < func.now(),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Update ────────────────────────────────────────────────

    async def update(
        self,
        report_id: uuid.UUID,
        *,
        expected_version: int,
        **fields: Any,
    ) -> Report | None:
        """Update report fields with optimistic locking.

        The ``expected_version`` must match the current database version.
        On success the version is incremented.  Returns ``None`` if the
        report is not found or the version has changed (optimistic lock
        conflict).

        Parameters
        ----------
        report_id:
            UUID of the report to update.
        expected_version:
            The version the caller believes is current.
        **fields:
            Column names and their new values.
        """
        if not fields:
            return await self.get_by_id(report_id)

        # Filter out None-valued fields to allow partial updates
        update_data = {k: v for k, v in fields.items() if v is not None}
        update_data["version"] = expected_version + 1
        update_data["updated_at"] = func.now()

        stmt = (
            update(Report)
            .where(Report.id == report_id, Report.version == expected_version)
            .values(**update_data)
            .returning(Report.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()

        if row is None:
            logger.warning(
                "report_update_conflict",
                report_id=str(report_id),
                expected_version=expected_version,
            )
            return None

        await self._session.flush()
        return await self.get_by_id(report_id)

    # ── Delete ────────────────────────────────────────────────

    async def delete(self, report_id: uuid.UUID) -> bool:
        """Delete a report by ID (cascade deletes messages/attachments).

        Used by the data retention task.  Returns ``True`` if a report
        was actually deleted, ``False`` if it didn't exist.
        """
        report = await self.get_by_id(report_id)
        if report is None:
            return False

        await self._session.delete(report)
        await self._session.flush()
        logger.info("report_deleted", report_id=str(report_id))
        return True

    # ── Search ────────────────────────────────────────────────

    async def full_text_search(
        self,
        query: str,
        *,
        pagination: PaginationParams,
    ) -> tuple[list[Report], PaginationMeta]:
        """Perform full-text search using the German tsvector index.

        Delegates to ``list_paginated`` with the ``search`` filter.
        """
        return await self.list_paginated(
            pagination=pagination,
            search=query,
        )

    # ── Private helpers ───────────────────────────────────────

    @staticmethod
    def _apply_eager_loading(
        stmt: Select[tuple[Report]],
        with_messages: bool,
        with_attachments: bool,
    ) -> Select[tuple[Report]]:
        """Optionally add eager-loading options to a select statement."""
        if with_messages:
            stmt = stmt.options(selectinload(Report.messages))
        if with_attachments:
            stmt = stmt.options(selectinload(Report.attachments))
        return stmt

    @staticmethod
    def _apply_filters(
        stmt: Select[tuple[Report]],
        *,
        status: ReportStatus | None = None,
        priority: Priority | None = None,
        channel: Channel | None = None,
        category: str | None = None,
        assigned_to: uuid.UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        overdue_only: bool = False,
    ) -> Select[tuple[Report]]:
        """Apply optional WHERE clauses to a report query."""
        if status is not None:
            stmt = stmt.where(Report.status == status)

        if priority is not None:
            stmt = stmt.where(Report.priority == priority)

        if channel is not None:
            stmt = stmt.where(Report.channel == channel)

        if category is not None:
            stmt = stmt.where(Report.category == category)

        if assigned_to is not None:
            stmt = stmt.where(Report.assigned_to == assigned_to)

        if date_from is not None:
            stmt = stmt.where(Report.created_at >= date_from)

        if date_to is not None:
            stmt = stmt.where(Report.created_at <= date_to)

        if search:
            # Use PostgreSQL to_tsquery with 'german' config.
            # Sanitise the input by replacing spaces with ' & ' for
            # AND semantics and wrapping each word with :* for prefix
            # matching.
            sanitised = " & ".join(
                f"{word}:*"
                for word in search.strip().split()
                if word
            )
            stmt = stmt.where(
                text("search_vector @@ to_tsquery('german', :q)").bindparams(
                    q=sanitised,
                )
            )

        if overdue_only:
            now = func.now()
            stmt = stmt.where(
                (
                    (Report.confirmation_deadline < now)
                    & (Report.confirmation_sent_at.is_(None))
                )
                | (
                    (Report.feedback_deadline < now)
                    & (Report.feedback_sent_at.is_(None))
                )
            )

        return stmt

    @staticmethod
    def _resolve_sort_column(sort_by: str) -> Any:
        """Map a sort field name to the corresponding model column.

        Falls back to ``created_at`` for unknown field names.
        """
        column_map: dict[str, Any] = {
            "created_at": Report.created_at,
            "updated_at": Report.updated_at,
            "status": Report.status,
            "priority": Report.priority,
            "case_number": Report.case_number,
            "channel": Report.channel,
            "confirmation_deadline": Report.confirmation_deadline,
            "feedback_deadline": Report.feedback_deadline,
        }
        return column_map.get(sort_by, Report.created_at)
