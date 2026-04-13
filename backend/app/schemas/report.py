"""Hinweisgebersystem – Report (Case) Pydantic Schemas.

Request and response schemas for the whistleblower report / case
endpoints.  Covers both HinSchG (internal) and LkSG (public) channels
with the LkSG-extended fields being optional and conditionally
validated.

Sensitive fields (subject, description, reporter identity) are handled
as plain strings in the schema layer — encryption/decryption is
transparent via the SQLAlchemy ``PGPString`` TypeDecorator at the ORM
level.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.report import (
    Channel,
    LkSGCategory,
    Priority,
    ReporterRelationship,
    ReportStatus,
    SupplyChainTier,
)
from app.schemas.common import PaginatedResponse, TimestampSchema, UUIDSchema
from app.schemas.label import LabelSummary


# ── Report Create (Reporter Submission) ──────────────────────


class ReportCreate(BaseModel):
    """Schema for submitting a new report (reporter-facing).

    The ``subject`` and ``description`` will be encrypted at the ORM
    layer via pgcrypto.  Reporter identity fields are required only
    when ``is_anonymous`` is ``False``.  LkSG-extended fields are
    required only when ``channel`` is ``lksg``.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_min_length=1,
    )

    # ── Core fields ───────────────────────────────────────────
    subject: str = Field(
        max_length=500,
        description="Report subject/title (will be encrypted).",
    )
    description: str = Field(
        max_length=50_000,
        description="Detailed report description (will be encrypted).",
    )
    channel: Channel = Field(
        default=Channel.HINSCHG,
        description="Reporting channel: HinSchG (internal) or LkSG (public).",
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Category key (references category_translations).",
    )
    language: str = Field(
        default="de",
        max_length=5,
        description="Reporter's preferred language (ISO 639-1).",
    )

    # ── Anonymity ─────────────────────────────────────────────
    is_anonymous: bool = Field(
        default=True,
        description="Whether the report is submitted anonymously.",
    )

    # ── Reporter identity (non-anonymous only) ────────────────
    reporter_name: str | None = Field(
        default=None,
        max_length=255,
        description="Reporter's name (non-anonymous only, will be encrypted).",
    )
    reporter_email: str | None = Field(
        default=None,
        max_length=255,
        description="Reporter's email (non-anonymous only, will be encrypted).",
    )
    reporter_phone: str | None = Field(
        default=None,
        max_length=50,
        description="Reporter's phone number (non-anonymous only, will be encrypted).",
    )

    # ── Self-chosen password (optional) ───────────────────────
    password: str | None = Field(
        default=None,
        min_length=10,
        max_length=128,
        description=(
            "Self-chosen password for mailbox access. "
            "If not provided, a 6-word passphrase will be generated."
        ),
    )

    # ── LkSG-extended fields ─────────────────────────────────
    country: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="ISO 3166-1 alpha-3 country code (LkSG reports).",
    )
    organization: str | None = Field(
        default=None,
        max_length=255,
        description="Reported organisation name (LkSG reports).",
    )
    supply_chain_tier: SupplyChainTier | None = Field(
        default=None,
        description="Supply chain tier (LkSG reports).",
    )
    reporter_relationship: ReporterRelationship | None = Field(
        default=None,
        description="Reporter's relationship to the reported organisation (LkSG).",
    )
    lksg_category: LkSGCategory | None = Field(
        default=None,
        description="LkSG-specific complaint category.",
    )

    # ── Bot protection ────────────────────────────────────────
    captcha_token: str | None = Field(
        default=None,
        description="hCaptcha response token for bot protection.",
    )

    @field_validator("country")
    @classmethod
    def validate_country_code(cls, v: str | None) -> str | None:
        """Ensure country code is uppercase ISO 3166-1 alpha-3."""
        if v is not None:
            return v.upper()
        return v


# ── Report Create Response ────────────────────────────────────


class ReportCreateResponse(BaseModel):
    """Response returned after successful report submission.

    Contains the case number and passphrase that the reporter must
    save to access their anonymous mailbox.  This is the **only** time
    the passphrase is shown in cleartext.

    Also includes a short-lived ``access_token`` so the frontend can
    upload file attachments immediately after submission (before the
    reporter navigates away or loses the passphrase).
    """

    model_config = ConfigDict(frozen=True)

    case_number: str = Field(
        description="16-character unique case identifier.",
    )
    report_id: str = Field(
        description="UUID of the newly created report.",
    )
    passphrase: str | None = Field(
        default=None,
        description=(
            "6-word BIP-39 passphrase for mailbox access.  "
            "Only returned when no self-chosen password was provided."
        ),
    )
    access_token: str = Field(
        description=(
            "Short-lived JWT session token for immediate file upload.  "
            "Valid for 10 minutes."
        ),
    )
    message: str = Field(
        default="Report submitted successfully.",
        description="Human-readable confirmation message.",
    )


# ── Report Response (Full) ────────────────────────────────────


class AttachmentSummary(BaseModel):
    """Minimal attachment info embedded in report responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    file_size: int
    created_at: datetime


class MessageSummary(BaseModel):
    """Minimal message info embedded in report responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_type: str
    is_internal: bool
    is_read: bool
    created_at: datetime


class ReportResponse(UUIDSchema, TimestampSchema):
    """Full report response for admin / handler views.

    Decrypted fields are returned as plain strings; the ORM layer
    handles transparent decryption via ``PGPString``.
    """

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    case_number: str
    is_anonymous: bool

    # ── Case metadata ─────────────────────────────────────────
    channel: Channel
    status: ReportStatus
    priority: Priority
    category: str | None = None
    language: str

    # ── Decrypted fields ──────────────────────────────────────
    subject: str | None = Field(
        default=None,
        alias="subject_encrypted",
        description="Decrypted report subject.",
    )
    description: str | None = Field(
        default=None,
        alias="description_encrypted",
        description="Decrypted report description.",
    )

    # ── Reporter identity (non-anonymous only) ────────────────
    reporter_name: str | None = Field(
        default=None,
        alias="reporter_name_encrypted",
        description="Decrypted reporter name.",
    )
    reporter_email: str | None = Field(
        default=None,
        alias="reporter_email_encrypted",
        description="Decrypted reporter email.",
    )
    reporter_phone: str | None = Field(
        default=None,
        alias="reporter_phone_encrypted",
        description="Decrypted reporter phone.",
    )

    # ── LkSG-extended fields ─────────────────────────────────
    country: str | None = None
    organization: str | None = None
    supply_chain_tier: SupplyChainTier | None = None
    reporter_relationship: ReporterRelationship | None = None
    lksg_category: LkSGCategory | None = None

    # ── Labels ───────────────────────────────────────────────────
    labels: list[LabelSummary] = Field(
        default_factory=list,
        description="Labels assigned to this report.",
    )

    # ── Sub-status ───────────────────────────────────────────────
    sub_status_id: UUID | None = None

    # ── Assignment & deadlines ────────────────────────────────
    assigned_to: UUID | None = None
    confirmation_deadline: datetime | None = None
    feedback_deadline: datetime | None = None
    confirmation_sent_at: datetime | None = None
    feedback_sent_at: datetime | None = None
    retention_until: datetime | None = None

    # ── Related ───────────────────────────────────────────────
    related_case_numbers: list[str] | None = None

    # ── Optimistic locking ────────────────────────────────────
    version: int


# ── Report Response (Mailbox / Reporter View) ────────────────


class ReportMailboxResponse(BaseModel):
    """Limited report response for the anonymous mailbox view.

    Excludes internal-only fields (assigned_to, priority, internal
    notes) to prevent information leakage to the reporter.
    """

    model_config = ConfigDict(from_attributes=True)

    case_number: str
    channel: Channel
    status: ReportStatus
    category: str | None = None
    language: str
    subject: str | None = Field(
        default=None,
        alias="subject_encrypted",
    )
    created_at: datetime
    updated_at: datetime

    # ── LkSG fields (visible to reporter) ─────────────────────
    country: str | None = None
    organization: str | None = None
    lksg_category: LkSGCategory | None = None


# ── Report Update (Admin) ────────────────────────────────────


class ReportUpdate(BaseModel):
    """Schema for updating report metadata (admin-facing).

    Only case management fields can be updated — encrypted content
    cannot be modified after submission.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    status: ReportStatus | None = Field(
        default=None,
        description="New case status.",
    )
    priority: Priority | None = Field(
        default=None,
        description="New case priority.",
    )
    assigned_to: UUID | None = Field(
        default=None,
        description="User ID to assign the case to.",
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Updated category key.",
    )
    sub_status_id: UUID | None = Field(
        default=None,
        description=(
            "UUID of the sub-status to assign.  When the main status "
            "changes and this field is not provided, the sub-status is "
            "automatically cleared."
        ),
    )
    related_case_numbers: list[str] | None = Field(
        default=None,
        description="Updated list of related case numbers.",
    )
    version: int = Field(
        description="Current version for optimistic locking (must match DB).",
    )


# ── Report List Filters ──────────────────────────────────────


class ReportListFilters(BaseModel):
    """Query parameters for filtering the case list."""

    model_config = ConfigDict(frozen=True)

    status: ReportStatus | None = Field(
        default=None,
        description="Filter by case status.",
    )
    priority: Priority | None = Field(
        default=None,
        description="Filter by priority.",
    )
    channel: Channel | None = Field(
        default=None,
        description="Filter by reporting channel.",
    )
    category: str | None = Field(
        default=None,
        description="Filter by category key.",
    )
    assigned_to: UUID | None = Field(
        default=None,
        description="Filter by assigned handler.",
    )
    search: str | None = Field(
        default=None,
        max_length=500,
        description="Full-text search query (German tsvector).",
    )
    date_from: datetime | None = Field(
        default=None,
        description="Filter reports created on or after this date.",
    )
    date_to: datetime | None = Field(
        default=None,
        description="Filter reports created on or before this date.",
    )
    overdue_only: bool = Field(
        default=False,
        description="Show only cases with overdue deadlines.",
    )


# ── Paginated Report List ─────────────────────────────────────


class ReportListResponse(PaginatedResponse[ReportResponse]):
    """Paginated list of reports for the admin dashboard."""

    pass
