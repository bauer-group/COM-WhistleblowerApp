"""Hinweisgebersystem – Message Repository.

Encapsulates database access for the ``Message`` model including:
- Creating messages (reporter, handler, or system)
- Listing messages per report (with internal note filtering)
- Marking messages as read
- Counting unread messages

All queries run within the RLS-scoped session provided by
``get_db()`` so that tenant isolation is enforced at the database
level.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.message import Message, SenderType

logger = structlog.get_logger(__name__)


class MessageRepository:
    """Data access layer for report messages.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Create ────────────────────────────────────────────────

    async def create(self, message: Message) -> Message:
        """Insert a new message and return it with generated defaults.

        The caller is responsible for populating ``report_id``,
        ``tenant_id``, ``sender_type``, and the encrypted content.
        """
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message)
        logger.info(
            "message_created",
            report_id=str(message.report_id),
            sender_type=message.sender_type.value,
            is_internal=message.is_internal,
        )
        return message

    # ── Read (single) ─────────────────────────────────────────

    async def get_by_id(
        self,
        message_id: uuid.UUID,
        *,
        with_attachments: bool = False,
    ) -> Message | None:
        """Fetch a single message by primary key.

        Returns ``None`` if not found or filtered by RLS.
        """
        stmt = select(Message).where(Message.id == message_id)
        if with_attachments:
            stmt = stmt.options(selectinload(Message.attachments))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Read (list) ───────────────────────────────────────────

    async def list_by_report(
        self,
        report_id: uuid.UUID,
        *,
        include_internal: bool = True,
        with_attachments: bool = False,
    ) -> list[Message]:
        """List all messages for a given report, ordered by creation time.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        include_internal:
            If ``False``, internal handler notes (``is_internal=True``)
            are excluded.  This is used for the reporter mailbox view
            where internal notes must not be visible.
        with_attachments:
            Eagerly load attachments for each message.
        """
        stmt = (
            select(Message)
            .where(Message.report_id == report_id)
            .order_by(Message.created_at.asc())
        )

        if not include_internal:
            stmt = stmt.where(Message.is_internal.is_(False))

        if with_attachments:
            stmt = stmt.options(selectinload(Message.attachments))

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_report_for_mailbox(
        self,
        report_id: uuid.UUID,
    ) -> list[Message]:
        """List messages visible to the reporter (excludes internal notes).

        Convenience wrapper around ``list_by_report`` for the mailbox
        endpoints.
        """
        return await self.list_by_report(
            report_id,
            include_internal=False,
            with_attachments=True,
        )

    # ── Update ────────────────────────────────────────────────

    async def mark_as_read(
        self,
        message_id: uuid.UUID,
    ) -> Message | None:
        """Mark a single message as read.

        Returns the updated message or ``None`` if not found.
        """
        stmt = (
            update(Message)
            .where(Message.id == message_id)
            .values(is_read=True)
            .returning(Message.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()
        if row is None:
            return None

        await self._session.flush()
        return await self.get_by_id(message_id)

    async def mark_all_as_read(
        self,
        report_id: uuid.UUID,
        *,
        sender_type: SenderType | None = None,
    ) -> int:
        """Mark all messages in a report as read.

        Optionally filter by ``sender_type`` to mark only messages from
        a specific sender (e.g. mark all reporter messages as read when
        a handler opens the case).

        Returns the number of messages updated.
        """
        stmt = (
            update(Message)
            .where(
                Message.report_id == report_id,
                Message.is_read.is_(False),
            )
            .values(is_read=True)
        )

        if sender_type is not None:
            stmt = stmt.where(Message.sender_type == sender_type)

        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

    # ── Counts ────────────────────────────────────────────────

    async def count_unread(
        self,
        report_id: uuid.UUID,
        *,
        sender_type: SenderType | None = None,
    ) -> int:
        """Count unread messages for a report.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        sender_type:
            Optionally count only messages from a specific sender type.
            For example, count unread reporter messages to show a badge
            in the admin case list.
        """
        stmt = select(func.count()).select_from(Message).where(
            Message.report_id == report_id,
            Message.is_read.is_(False),
        )

        if sender_type is not None:
            stmt = stmt.where(Message.sender_type == sender_type)

        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_by_report(self, report_id: uuid.UUID) -> int:
        """Count total messages for a report."""
        stmt = select(func.count()).select_from(Message).where(
            Message.report_id == report_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
