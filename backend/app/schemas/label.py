"""Hinweisgebersystem – Label Pydantic Schemas.

Request and response schemas for label management endpoints.
Labels are tenant-scoped tags that can be assigned to reports
for flexible categorisation and filtering (e.g. ``"Urgent"``,
``"Compliance"``, ``"Follow-up needed"``).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse, TimestampSchema, UUIDSchema


# ── Label Create ──────────────────────────────────────────────


class LabelCreate(BaseModel):
    """Schema for creating a new label.

    Labels are tenant-scoped and identified by a human-readable
    ``name``.  An optional ``color`` hex code and ``description``
    can be provided for UI display.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Human-readable label name (e.g. 'Urgent').",
    )
    color: str = Field(
        default="#6B7280",
        min_length=4,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{3,6}$",
        description="Hex colour code for UI display (e.g. '#FF5733').",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of the label's purpose.",
    )


# ── Label Update ──────────────────────────────────────────────


class LabelUpdate(BaseModel):
    """Schema for updating an existing label.

    All fields are optional -- only provided fields will be updated.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Updated label name.",
    )
    color: str | None = Field(
        default=None,
        min_length=4,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{3,6}$",
        description="Updated hex colour code.",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Updated description.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the label.",
    )


# ── Label Response ────────────────────────────────────────────


class LabelResponse(UUIDSchema, TimestampSchema):
    """Full label response for admin label management views."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    name: str
    color: str
    description: str | None = None
    is_active: bool


# ── Label Summary (embedded in other responses) ──────────────


class LabelSummary(BaseModel):
    """Minimal label info embedded in report/case responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: str


# ── Label Assignment ──────────────────────────────────────────


class LabelAssignment(BaseModel):
    """Schema for assigning or removing a label from a report."""

    model_config = ConfigDict(frozen=True)

    label_id: UUID = Field(
        description="UUID of the label to assign or remove.",
    )


# ── Paginated Label List ─────────────────────────────────────


class LabelListResponse(PaginatedResponse[LabelResponse]):
    """Paginated list of labels for label management."""

    pass
