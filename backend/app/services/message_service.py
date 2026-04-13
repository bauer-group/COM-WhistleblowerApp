"""Hinweisgebersystem -- Message Business Service.

Orchestrates bidirectional communication between reporters and case
handlers in the anonymous mailbox system.  Provides:

- **Create messages**: from reporter, handler, or system, with
  channel-appropriate validation and audit logging.
- **Internal notes**: handler-only notes invisible to the reporter.
- **Read management**: mark messages as read individually or in bulk.
- **Listing**: messages per report with internal-note filtering for
  mailbox vs admin views.
- **System messages**: auto-generated notifications for status changes,
  assignment changes, and other lifecycle events.

Message content is passed as plain strings to the ORM layer where
``PGPString`` handles transparent encryption via pgcrypto.

Usage::

    from app.services.message_service import MessageService

    service = MessageService(session, tenant_id)
    message = await service.create_reporter_message(report_id, content)
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.message import Message, SenderType
from app.repositories.audit_repo import AuditRepository
from app.repositories.message_repo import MessageRepository

logger = structlog.get_logger(__name__)


class MessageService:
    """Business logic for report messages and communication.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    tenant_id:
        UUID of the current tenant (from middleware).
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._message_repo = MessageRepository(session)
        self._audit_repo = AuditRepository(session)

    # ── Create (reporter) ────────────────────────────────────

    async def create_reporter_message(
        self,
        report_id: uuid.UUID,
        content: str,
    ) -> Message:
        """Create a message from the anonymous reporter.

        Reporter messages are never internal and always visible to
        handlers.  The ``sender_user_id`` is ``None`` because the
        reporter is anonymous.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        content:
            Message body (will be encrypted at ORM level).

        Returns
        -------
        Message
            The persisted message instance.
        """
        message = Message(
            report_id=report_id,
            tenant_id=self._tenant_id,
            sender_type=SenderType.REPORTER,
            sender_user_id=None,
            is_internal=False,
            is_read=False,
        )
        # PGPString handles encryption transparently
        message.content_encrypted = content  # type: ignore[assignment]

        message = await self._message_repo.create(message)

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.MESSAGE_SENT,
            resource_type="message",
            resource_id=str(message.id),
            actor_type="reporter",
            details={
                "report_id": str(report_id),
                "sender_type": SenderType.REPORTER.value,
            },
        )

        logger.info(
            "reporter_message_created",
            report_id=str(report_id),
            message_id=str(message.id),
        )

        return message

    # ── Create (handler) ─────────────────────────────────────

    async def create_handler_message(
        self,
        report_id: uuid.UUID,
        content: str,
        sender_user_id: uuid.UUID,
        *,
        is_internal: bool = False,
    ) -> Message:
        """Create a message from a case handler.

        Handlers can send messages visible to the reporter (for the
        anonymous mailbox) or create internal notes visible only to
        other handlers.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        content:
            Message body (will be encrypted at ORM level).
        sender_user_id:
            UUID of the handler sending the message.
        is_internal:
            If ``True``, the message is an internal note invisible
            to the reporter.

        Returns
        -------
        Message
            The persisted message instance.
        """
        message = Message(
            report_id=report_id,
            tenant_id=self._tenant_id,
            sender_type=SenderType.HANDLER,
            sender_user_id=sender_user_id,
            is_internal=is_internal,
            is_read=False,
        )
        message.content_encrypted = content  # type: ignore[assignment]

        message = await self._message_repo.create(message)

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.MESSAGE_SENT,
            resource_type="message",
            resource_id=str(message.id),
            actor_id=sender_user_id,
            actor_type="user",
            details={
                "report_id": str(report_id),
                "sender_type": SenderType.HANDLER.value,
                "is_internal": is_internal,
            },
        )

        logger.info(
            "handler_message_created",
            report_id=str(report_id),
            message_id=str(message.id),
            is_internal=is_internal,
        )

        return message

    # ── Create (system) ──────────────────────────────────────

    async def create_system_message(
        self,
        report_id: uuid.UUID,
        content: str,
    ) -> Message:
        """Create an auto-generated system message.

        System messages are generated for lifecycle events such as
        status changes, handler assignment, and deadline notifications.
        They are visible to both reporters and handlers (never internal).

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        content:
            System-generated message body.

        Returns
        -------
        Message
            The persisted message instance.
        """
        message = Message(
            report_id=report_id,
            tenant_id=self._tenant_id,
            sender_type=SenderType.SYSTEM,
            sender_user_id=None,
            is_internal=False,
            is_read=False,
        )
        message.content_encrypted = content  # type: ignore[assignment]

        message = await self._message_repo.create(message)

        logger.info(
            "system_message_created",
            report_id=str(report_id),
            message_id=str(message.id),
        )

        return message

    # ── Get or create initial message (for direct file uploads) ─

    async def get_or_create_initial_message(
        self,
        report_id: uuid.UUID,
    ) -> Message:
        """Return the first message for a report, creating one if needed.

        Used by the direct file upload endpoint so reporters can attach
        files immediately after report creation without sending a
        separate text message first.
        """
        messages = await self._message_repo.list_by_report(
            report_id,
            include_internal=False,
            with_attachments=False,
        )
        # Return the first reporter/system message if one exists.
        for msg in messages:
            if msg.sender_type in (SenderType.REPORTER, SenderType.SYSTEM):
                return msg

        # Create a system message as a container for initial attachments.
        message = Message(
            report_id=report_id,
            tenant_id=self._tenant_id,
            sender_type=SenderType.SYSTEM,
            sender_user_id=None,
            is_internal=False,
            is_read=False,
        )
        message.content_encrypted = "Initial report attachments"  # type: ignore[assignment]
        return await self._message_repo.create(message)

    # ── Read (single) ────────────────────────────────────────

    async def get_message_by_id(
        self,
        message_id: uuid.UUID,
        *,
        with_attachments: bool = False,
    ) -> Message | None:
        """Fetch a single message by ID.

        Returns ``None`` if not found or filtered by RLS.
        """
        return await self._message_repo.get_by_id(
            message_id,
            with_attachments=with_attachments,
        )

    # ── Read (list) ──────────────────────────────────────────

    async def list_messages_for_admin(
        self,
        report_id: uuid.UUID,
        *,
        with_attachments: bool = True,
    ) -> list[Message]:
        """List all messages for a report (admin/handler view).

        Includes internal notes which are only visible to handlers.

        Parameters
        ----------
        report_id:
            UUID of the parent report.
        with_attachments:
            Eagerly load attachments for each message.
        """
        return await self._message_repo.list_by_report(
            report_id,
            include_internal=True,
            with_attachments=with_attachments,
        )

    async def list_messages_for_mailbox(
        self,
        report_id: uuid.UUID,
    ) -> list[Message]:
        """List messages visible to the reporter (mailbox view).

        Excludes internal handler notes to prevent information leakage.
        """
        return await self._message_repo.list_by_report_for_mailbox(report_id)

    # ── Mark as read ─────────────────────────────────────────

    async def mark_message_read(
        self,
        message_id: uuid.UUID,
    ) -> Message | None:
        """Mark a single message as read.

        Returns the updated message or ``None`` if not found.
        """
        message = await self._message_repo.mark_as_read(message_id)

        if message is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.MESSAGE_READ,
                resource_type="message",
                resource_id=str(message_id),
                details={"report_id": str(message.report_id)},
            )

        return message

    async def mark_messages_read(
        self,
        message_ids: list[uuid.UUID],
    ) -> int:
        """Mark multiple messages as read.

        Returns the total number of messages updated.
        """
        total_updated = 0
        for message_id in message_ids:
            result = await self._message_repo.mark_as_read(message_id)
            if result is not None:
                total_updated += 1

        return total_updated

    async def mark_all_reporter_messages_read(
        self,
        report_id: uuid.UUID,
    ) -> int:
        """Mark all reporter messages in a report as read.

        Used when a handler opens a case -- automatically marks all
        unread reporter messages as read.

        Returns the number of messages updated.
        """
        return await self._message_repo.mark_all_as_read(
            report_id,
            sender_type=SenderType.REPORTER,
        )

    async def mark_all_handler_messages_read(
        self,
        report_id: uuid.UUID,
    ) -> int:
        """Mark all handler/system messages as read.

        Used when a reporter opens their mailbox -- automatically
        marks all unread handler and system messages as read.

        Returns the number of messages updated.
        """
        return await self._message_repo.mark_all_as_read(
            report_id,
            sender_type=SenderType.HANDLER,
        )

    # ── Counts ───────────────────────────────────────────────

    async def count_unread_for_handler(
        self,
        report_id: uuid.UUID,
    ) -> int:
        """Count unread reporter messages for a report.

        Used to display an unread badge on the admin case list.
        """
        return await self._message_repo.count_unread(
            report_id,
            sender_type=SenderType.REPORTER,
        )

    async def count_unread_for_reporter(
        self,
        report_id: uuid.UUID,
    ) -> int:
        """Count unread handler/system messages for a report.

        Used to display an unread badge in the reporter mailbox.
        """
        return await self._message_repo.count_unread(
            report_id,
            sender_type=SenderType.HANDLER,
        )

    async def count_total_messages(
        self,
        report_id: uuid.UUID,
    ) -> int:
        """Count total messages for a report."""
        return await self._message_repo.count_by_report(report_id)

    # ── System message helpers ───────────────────────────────
    # Convenience methods for common lifecycle events.

    async def notify_status_change(
        self,
        report_id: uuid.UUID,
        old_status: str,
        new_status: str,
    ) -> Message:
        """Create a system message for a status change event.

        Parameters
        ----------
        report_id:
            UUID of the report.
        old_status:
            Previous status value.
        new_status:
            New status value.
        """
        content = (
            f"Der Fallstatus wurde von '{old_status}' "
            f"auf '{new_status}' geaendert."
        )
        return await self.create_system_message(report_id, content)

    async def notify_handler_assigned(
        self,
        report_id: uuid.UUID,
    ) -> Message:
        """Create a system message when a handler is assigned."""
        content = (
            "Ein Sachbearbeiter wurde Ihrem Fall zugewiesen. "
            "Sie erhalten in Kuerze eine Rueckmeldung."
        )
        return await self.create_system_message(report_id, content)

    async def notify_confirmation_sent(
        self,
        report_id: uuid.UUID,
    ) -> Message:
        """Create a system message for the 7-day confirmation."""
        content = (
            "Wir bestaetigen den Eingang Ihrer Meldung. "
            "Ihr Fall wird geprueft und bearbeitet."
        )
        return await self.create_system_message(report_id, content)
