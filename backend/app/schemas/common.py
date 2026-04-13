"""Hinweisgebersystem – Common Pydantic Schemas.

Shared schemas used across the API for pagination, error responses,
and health checks.  All schemas use Pydantic v2 with ``model_config``
instead of the v1 ``Config`` inner class.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ── Pagination ────────────────────────────────────────────────


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(
        default=1,
        ge=1,
        description="Page number (1-indexed).",
    )
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of items per page (max 100).",
    )


class PaginationMeta(BaseModel):
    """Pagination metadata included in paginated responses."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(description="Current page number (1-indexed).")
    page_size: int = Field(description="Number of items per page.")
    total: int = Field(description="Total number of items matching the query.")
    total_pages: int = Field(description="Total number of pages.")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper.

    Usage::

        PaginatedResponse[ReportResponse](
            items=[...],
            pagination=PaginationMeta(...),
        )
    """

    items: list[T]
    pagination: PaginationMeta


# ── Error Response ────────────────────────────────────────────


class ErrorDetail(BaseModel):
    """Individual error detail entry."""

    model_config = ConfigDict(frozen=True)

    field: str | None = Field(
        default=None,
        description="Field name that caused the error (if applicable).",
    )
    message: str = Field(description="Human-readable error message.")
    code: str | None = Field(
        default=None,
        description="Machine-readable error code.",
    )


class ErrorResponse(BaseModel):
    """Standard error response returned by all API error handlers."""

    model_config = ConfigDict(frozen=True)

    detail: str = Field(description="Human-readable error summary.")
    status_code: int = Field(description="HTTP status code.")
    errors: list[ErrorDetail] | None = Field(
        default=None,
        description="Detailed validation errors (for 422 responses).",
    )


# ── Health Check ──────────────────────────────────────────────


class HealthCheck(BaseModel):
    """Response schema for the ``/health`` endpoint."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        default="ok",
        description="Service health status.",
        examples=["ok", "degraded"],
    )
    version: str = Field(
        description="Application version string.",
        examples=["1.0.0"],
    )
    timestamp: datetime = Field(
        description="Current server timestamp (UTC).",
    )


# ── UUID Mixin ────────────────────────────────────────────────


class UUIDSchema(BaseModel):
    """Base schema for responses that include a UUID primary key."""

    id: UUID = Field(description="Unique identifier.")


class TimestampSchema(BaseModel):
    """Mixin for schemas that include created/updated timestamps."""

    created_at: datetime = Field(description="Creation timestamp (UTC).")
    updated_at: datetime = Field(description="Last update timestamp (UTC).")
