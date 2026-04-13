"""Hinweisgebersystem – Report (Case) ORM Model.

The ``Report`` model is the central entity of the whistleblower system.
It stores submitted reports from both HinSchG (internal) and LkSG (public)
channels.  Sensitive fields (subject, description, reporter identity) are
encrypted at rest via pgcrypto using the per-tenant DEK.

The model supports:
- Anonymous and non-anonymous submissions
- LkSG-extended data fields (country, organisation, supply chain tier)
- Dual-credential mailbox access (passphrase OR self-chosen password)
- Optimistic locking via ``version`` column
- German full-text search via ``search_vector`` (tsvector)
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import ARRAY

from app.core.database import Base
from app.models.types import PGPString

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.identity_disclosure import IdentityDisclosure
    from app.models.label import Label
    from app.models.message import Message
    from app.models.substatus import SubStatus
    from app.models.tenant import Tenant


# ── Association Tables ────────────────────────────────────────

report_labels = Table(
    "report_labels",
    Base.metadata,
    Column(
        "report_id",
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "label_id",
        UUID(as_uuid=True),
        ForeignKey("labels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ── Enums ─────────────────────────────────────────────────────


class ReportStatus(str, enum.Enum):
    """Case lifecycle statuses per HinSchG workflow."""

    EINGEGANGEN = "eingegangen"
    IN_PRUEFUNG = "in_pruefung"
    IN_BEARBEITUNG = "in_bearbeitung"
    RUECKMELDUNG = "rueckmeldung"
    ABGESCHLOSSEN = "abgeschlossen"


class Priority(str, enum.Enum):
    """Case priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Channel(str, enum.Enum):
    """Reporting channel type."""

    HINSCHG = "hinschg"
    LKSG = "lksg"


class ReporterRelationship(str, enum.Enum):
    """Reporter's relationship to the reported organisation (LkSG)."""

    EMPLOYEE = "employee"
    SUPPLIER = "supplier"
    CONTRACTOR = "contractor"
    COMMUNITY_MEMBER = "community_member"
    NGO = "ngo"
    OTHER = "other"


class SupplyChainTier(str, enum.Enum):
    """Supply chain tier for LkSG reports."""

    OWN_OPERATIONS = "own_operations"
    DIRECT_SUPPLIER = "direct_supplier"
    INDIRECT_SUPPLIER = "indirect_supplier"
    UNKNOWN = "unknown"


class LkSGCategory(str, enum.Enum):
    """LkSG-specific complaint categories."""

    CHILD_LABOR = "child_labor"
    FORCED_LABOR = "forced_labor"
    DISCRIMINATION = "discrimination"
    FREEDOM_OF_ASSOCIATION = "freedom_of_association"
    WORKING_CONDITIONS = "working_conditions"
    FAIR_WAGES = "fair_wages"
    ENVIRONMENTAL_DAMAGE = "environmental_damage"
    LAND_RIGHTS = "land_rights"
    SECURITY_FORCES = "security_forces"
    OTHER_HUMAN_RIGHTS = "other_human_rights"
    OTHER_ENVIRONMENTAL = "other_environmental"


# ── Report Model ──────────────────────────────────────────────


class Report(Base):
    """Whistleblower report / case.

    Encrypted fields use the ``PGPString`` TypeDecorator so that
    pgcrypto transparently encrypts on write and decrypts on read.
    The ``passphrase`` argument references the per-tenant DEK which
    is resolved at query time.

    Attributes
    ----------
    case_number : str
        16-character unique case identifier shown to the reporter.
    passphrase_hash : str
        bcrypt hash of the system-generated 6-word passphrase or
        the reporter's self-chosen password.
    channel : Channel
        Whether this is an internal HinSchG or public LkSG report.
    subject_encrypted : str
        Encrypted subject/title of the report.
    description_encrypted : str
        Encrypted description text.
    reporter_name_encrypted : str | None
        Encrypted reporter name (non-anonymous only).
    reporter_email_encrypted : str | None
        Encrypted reporter email (non-anonymous only).
    reporter_phone_encrypted : str | None
        Encrypted reporter phone number (non-anonymous only).
    """

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_number: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        nullable=False,
        index=True,
        comment="16-char case identifier shown to reporter",
    )

    # ── Authentication ────────────────────────────────────────
    passphrase_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash of passphrase or self-chosen password",
    )
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # ── Case metadata ─────────────────────────────────────────
    channel: Mapped[Channel] = mapped_column(
        Enum(Channel, name="channel_type", create_constraint=True),
        nullable=False,
        default=Channel.HINSCHG,
        index=True,
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status", create_constraint=True),
        nullable=False,
        default=ReportStatus.EINGEGANGEN,
        index=True,
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="priority_level", create_constraint=True),
        nullable=False,
        default=Priority.MEDIUM,
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Category key (references category_translations)",
    )
    sub_status_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sub_statuses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional configurable sub-status within the current status",
    )

    # ── Encrypted fields (pgcrypto via PGPString) ─────────────
    # NOTE: The passphrase for PGPString is the per-tenant DEK.
    # At model-definition time we use a placeholder; the actual DEK
    # is injected at query time via the encryption service layer.
    # For ORM definition, we set a config-level default that will
    # be overridden by the encryption middleware/service.
    subject_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted report subject",
    )
    description_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted report description",
    )
    reporter_name_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted reporter name (non-anonymous)",
    )
    reporter_email_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted reporter email (non-anonymous)",
    )
    reporter_phone_encrypted: Mapped[bytes | None] = mapped_column(
        PGPString("placeholder_dek"),
        nullable=True,
        comment="Encrypted reporter phone (non-anonymous)",
    )

    # ── LkSG-extended fields ──────────────────────────────────
    country: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        comment="ISO 3166-1 alpha-3 country code (LkSG)",
    )
    organization: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Reported organisation name (LkSG)",
    )
    supply_chain_tier: Mapped[SupplyChainTier | None] = mapped_column(
        Enum(SupplyChainTier, name="supply_chain_tier", create_constraint=True),
        nullable=True,
    )
    reporter_relationship: Mapped[ReporterRelationship | None] = mapped_column(
        Enum(ReporterRelationship, name="reporter_relationship", create_constraint=True),
        nullable=True,
    )
    lksg_category: Mapped[LkSGCategory | None] = mapped_column(
        Enum(LkSGCategory, name="lksg_category", create_constraint=True),
        nullable=True,
    )

    # ── Case assignment ───────────────────────────────────────
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Retention ─────────────────────────────────────────────
    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Auto-delete after this date (3y HinSchG, 7y LkSG)",
    )

    # ── Language ──────────────────────────────────────────────
    language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="de",
        server_default="de",
        comment="Reporter's preferred language (ISO 639-1)",
    )

    # ── Full-text search ──────────────────────────────────────
    # The tsvector column is maintained via a database trigger or
    # application-level update.  The GIN index is created in the
    # Alembic migration.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR(),
        nullable=True,
        comment="tsvector for German full-text search (maintained by trigger)",
    )

    # ── Related cases ─────────────────────────────────────────
    related_case_numbers: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(16)),
        nullable=True,
        default=list,
        comment="Case numbers of related reports",
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Optimistic locking ────────────────────────────────────
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Optimistic locking version",
    )

    # ── Deadlines ─────────────────────────────────────────────
    confirmation_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="7-day confirmation deadline (HinSchG §28)",
    )
    feedback_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="3-month feedback deadline (HinSchG §28)",
    )
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    feedback_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="reports",
        lazy="selectin",
    )
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="report",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment",
        back_populates="report",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    identity_disclosures: Mapped[list[IdentityDisclosure]] = relationship(
        "IdentityDisclosure",
        back_populates="report",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    labels: Mapped[list[Label]] = relationship(
        "Label",
        secondary="report_labels",
        back_populates="reports",
        lazy="selectin",
    )
    sub_status: Mapped[SubStatus | None] = relationship(
        "SubStatus",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Report case={self.case_number!r} "
            f"status={self.status.value!r} "
            f"channel={self.channel.value!r}>"
        )
