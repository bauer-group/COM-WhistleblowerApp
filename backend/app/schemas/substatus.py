"""Hinweisgebersystem – SubStatus Pydantic Schemas.

Request and response schemas for sub-status management endpoints.
Sub-statuses are tenant-scoped refinements of the five fixed HinSchG
case lifecycle statuses (e.g. ``"Waiting for external input"`` under
``in_bearbeitung``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.report import ReportStatus
from app.schemas.common import PaginatedResponse, UUIDSchema


# ── SubStatus Create ────────────────────────────────────────


class SubStatusCreate(BaseModel):
    """Schema for creating a new sub-status.

    Sub-statuses are tenant-scoped and linked to a fixed parent
    ``ReportStatus``.  The ``name`` must be unique within the
    tenant + parent status combination.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_status: ReportStatus = Field(
        description="Fixed HinSchG lifecycle status this sub-status refines.",
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable sub-status label (e.g. 'Waiting for feedback').",
    )
    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order within the parent status group (ascending).",
    )
    is_default: bool = Field(
        default=False,
        description=(
            "Whether this sub-status is automatically assigned when a "
            "report transitions to the parent status."
        ),
    )


# ── SubStatus Update ────────────────────────────────────────


class SubStatusUpdate(BaseModel):
    """Schema for updating an existing sub-status.

    All fields are optional -- only provided fields will be updated.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated sub-status label.",
    )
    display_order: int | None = Field(
        default=None,
        ge=0,
        description="Updated sort order.",
    )
    is_default: bool | None = Field(
        default=None,
        description="Updated default flag.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the sub-status.",
    )


# ── SubStatus Response ──────────────────────────────────────


class SubStatusResponse(UUIDSchema):
    """Full sub-status response for admin management views."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    parent_status: ReportStatus
    name: str
    display_order: int
    is_default: bool
    is_active: bool
    created_at: datetime


# ── SubStatus Summary (embedded in other responses) ─────────


class SubStatusSummary(BaseModel):
    """Minimal sub-status info embedded in report/case responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_status: ReportStatus
    name: str


# ── Paginated SubStatus List ────────────────────────────────


class SubStatusListResponse(PaginatedResponse[SubStatusResponse]):
    """Paginated list of sub-statuses for management views."""

    pass
