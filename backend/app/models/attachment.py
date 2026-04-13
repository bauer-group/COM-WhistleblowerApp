"""Hinweisgebersystem – Attachment ORM Model.

Attachment metadata for files uploaded to MinIO.  The actual file
content is encrypted with AES-256-GCM before upload; this model
stores the metadata needed to locate and decrypt the file.

Each attachment is linked to a report and optionally to a specific
message.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.report import Report


class Attachment(Base):
    """File attachment metadata.

    The file content is stored in MinIO, encrypted with AES-256-GCM.
    This model stores the MinIO object key, the encryption key
    (itself encrypted via envelope encryption), and integrity data.

    Attributes
    ----------
    storage_key : str
        MinIO object key (path within the bucket).
    original_filename : str
        User-provided filename for download.
    content_type : str
        MIME type of the original file.
    file_size : int
        Size of the original (unencrypted) file in bytes.
    encryption_key_ciphertext : str
        Per-file AES-256-GCM key, encrypted with the tenant DEK
        via envelope encryption (hex-encoded).
    sha256_hash : str
        SHA-256 hash of the original (unencrypted) file for
        integrity verification.
    """

    __tablename__ = "attachments"

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
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="NULL for attachments from initial report submission",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── File metadata ─────────────────────────────────────────
    storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="MinIO object key",
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User-provided filename",
    )
    content_type: Mapped[str] = mapped_column(
        String(127),
        nullable=False,
        default="application/octet-stream",
        comment="MIME type",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Original file size in bytes",
    )

    # ── Encryption metadata ───────────────────────────────────
    encryption_key_ciphertext: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Envelope-encrypted per-file AES-256-GCM key (hex)",
    )
    sha256_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of original file",
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
        back_populates="attachments",
        lazy="selectin",
    )
    message: Mapped[Message | None] = relationship(
        "Message",
        back_populates="attachments",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Attachment filename={self.original_filename!r} "
            f"size={self.file_size}>"
        )
