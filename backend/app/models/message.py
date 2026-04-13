"""Hinweisgebersystem – Message ORM Model.

Messages represent bidirectional communication between the reporter
(via anonymous mailbox) and case handlers.  Message content is
encrypted at rest via pgcrypto using the per-tenant DEK.

Internal notes (visible only to handlers) are stored as messages with
``is_internal=True``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.types import PGPString

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.report import Report


# ── Enums ─────────────────────────────────────────────────────


class SenderType(str, enum.Enum):
    """Who sent the message."""

    REPORTER = "reporter"
    HANDLER = "handler"
    SYSTEM = "system"


# ── Message Model ─────────────────────────────────────────────


class Message(Base):
    """Encrypted message in a report's communication thread.

    Attributes
    ----------
    content_encrypted : str
        Encrypted message body (pgcrypto).
    sender_type : SenderType
        Whether the message was sent by the reporter, a handler, or
        the system (e.g. auto-generated status change notices).
    sender_user_id : uuid | None
        For handler/system messages, the ID of the backend user.
        ``None`` for anonymous reporter messages.
    is_internal : bool
        Internal notes are visible only to handlers, never to the
        reporter via the mailbox.
    is_read : bool
        Whether the message has been read by the intended recipient.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Encrypted content ─────────────────────────────────────
    content_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted message body",
    )

    # ── Sender info ───────────────────────────────────────────
    sender_type: Mapped[SenderType] = mapped_column(
        Enum(SenderType, name="sender_type", create_constraint=True),
        nullable=False,
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Handler/system user ID (NULL for anonymous reporter)",
    )

    # ── Flags ─────────────────────────────────────────────────
    is_internal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Internal notes visible only to handlers",
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────
    report: Mapped[Report] = relationship(
        "Report",
        back_populates="messages",
        lazy="selectin",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment",
        back_populates="message",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id!r} "
            f"sender={self.sender_type.value!r} "
            f"internal={self.is_internal}>"
        )
