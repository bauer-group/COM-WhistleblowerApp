"""Hinweisgebersystem – Message Pydantic Schemas.

Request and response schemas for the message / communication endpoints.
Messages represent bidirectional communication in the anonymous mailbox
between reporters and case handlers.

Message content is handled as plain strings in the schema layer —
encryption/decryption is transparent via the SQLAlchemy ``PGPString``
TypeDecorator at the ORM level.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.message import SenderType
from app.schemas.common import PaginatedResponse, UUIDSchema
from app.schemas.report import AttachmentSummary


# ── Message Create (Reporter) ────────────────────────────────


class MessageCreate(BaseModel):
    """Schema for sending a message in the anonymous mailbox (reporter-facing).

    The reporter only provides the message content.  ``sender_type``
    is always ``REPORTER`` and is set server-side.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_min_length=1,
    )

    content: str = Field(
        max_length=50_000,
        description="Message body (will be encrypted).",
    )


# ── Message Create (Handler / Internal Note) ─────────────────


class MessageCreateHandler(BaseModel):
    """Schema for sending a message or internal note (handler-facing).

    Handlers can send messages visible to the reporter or create
    internal notes visible only to other handlers.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_min_length=1,
    )

    content: str = Field(
        max_length=50_000,
        description="Message body (will be encrypted).",
    )
    is_internal: bool = Field(
        default=False,
        description=(
            "If ``True``, the message is an internal note visible only "
            "to handlers, never shown to the reporter."
        ),
    )


# ── Message Response ──────────────────────────────────────────


class MessageResponse(UUIDSchema):
    """Full message response including decrypted content.

    Used in both admin case detail and reporter mailbox views.
    The service layer filters out ``is_internal=True`` messages
    when responding to reporter requests.
    """

    model_config = ConfigDict(from_attributes=True)

    report_id: UUID
    sender_type: SenderType
    sender_user_id: UUID | None = None
    is_internal: bool
    is_read: bool
    created_at: datetime

    # ── Decrypted content ─────────────────────────────────────
    content: str | None = Field(
        default=None,
        alias="content_encrypted",
        description="Decrypted message body.",
    )

    # ── Attachments ───────────────────────────────────────────
    attachments: list[AttachmentSummary] = Field(
        default_factory=list,
        description="File attachments associated with this message.",
    )


# ── Message Mailbox Response (Reporter View) ──────────────────


class MessageMailboxResponse(BaseModel):
    """Message response for the reporter mailbox view.

    Excludes internal notes and handler user IDs to protect handler
    identity from the reporter.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_type: SenderType
    is_read: bool
    created_at: datetime

    content: str | None = Field(
        default=None,
        alias="content_encrypted",
        description="Decrypted message body.",
    )

    attachments: list[AttachmentSummary] = Field(
        default_factory=list,
    )


# ── Message Mark Read ─────────────────────────────────────────


class MessageMarkRead(BaseModel):
    """Schema for marking messages as read."""

    model_config = ConfigDict(frozen=True)

    message_ids: list[UUID] = Field(
        min_length=1,
        description="List of message IDs to mark as read.",
    )


# ── Paginated Message List ────────────────────────────────────


class MessageListResponse(PaginatedResponse[MessageResponse]):
    """Paginated list of messages for a report."""

    pass
