"""Hinweisgebersystem – Admin Audit Log API Endpoints.

Provides:
- **GET /admin/audit-log** — Paginated audit log viewer with filters
  by action, actor, resource type, and date range.  Supports CSV
  export for compliance documentation.

All endpoints require OIDC-authenticated admin users with the
``audit:read`` scope.  Tenant isolation is enforced via Row-Level
Security (RLS).

Usage::

    from app.api.v1.admin_audit import router as admin_audit_router
    api_v1_router.include_router(admin_audit_router)
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Security, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.audit_log import AuditAction
from app.repositories.audit_repo import AuditRepository
from app.schemas.common import PaginatedResponse, PaginationParams

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/audit-log", tags=["admin-audit"])


# -- Response schemas ---------------------------------------------------------


class AuditLogEntryResponse(BaseModel):
    """Audit log entry returned by the audit log viewer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: AuditAction
    actor_id: uuid.UUID | None = None
    actor_type: str
    resource_type: str
    resource_id: str
    details: dict | None = None
    ip_address: str | None = None
    created_at: datetime


class AuditLogListResponse(PaginatedResponse[AuditLogEntryResponse]):
    """Paginated list of audit log entries."""

    pass


# -- GET /admin/audit-log ----------------------------------------------------


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List audit log entries with filters and pagination",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_audit_log(
    user=Security(get_current_user, scopes=["audit:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    # -- Pagination -----------------------------------------------------------
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)."
    ),
    # -- Filters --------------------------------------------------------------
    action: AuditAction | None = Query(
        default=None, description="Filter by audit action type."
    ),
    actor_id: uuid.UUID | None = Query(
        default=None, description="Filter by the acting user's ID."
    ),
    actor_type: str | None = Query(
        default=None, description="Filter by actor type (user, reporter, system)."
    ),
    resource_type: str | None = Query(
        default=None,
        description="Filter by resource type (report, user, tenant, etc.).",
    ),
    resource_id: str | None = Query(
        default=None, description="Filter by specific resource ID."
    ),
    date_from: datetime | None = Query(
        default=None, description="Filter entries created on or after this date."
    ),
    date_to: datetime | None = Query(
        default=None, description="Filter entries created on or before this date."
    ),
) -> AuditLogListResponse:
    """List audit log entries with filtering and pagination.

    Returns a paginated, reverse-chronological list of audit log entries.
    All filter parameters are optional and combined with ``AND``.

    This endpoint supports the compliance requirement to provide
    auditors with a complete, filterable view of all system actions.

    Requires ``audit:read`` scope (AUDITOR, TENANT_ADMIN, SYSTEM_ADMIN).
    """
    pagination = PaginationParams(page=page, page_size=page_size)
    audit_repo = AuditRepository(db)

    entries, meta = await audit_repo.list_paginated(
        pagination=pagination,
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        resource_type=resource_type,
        resource_id=resource_id,
        date_from=date_from,
        date_to=date_to,
    )

    items = [AuditLogEntryResponse.model_validate(entry) for entry in entries]

    logger.info(
        "admin_audit_log_listed",
        user_email=user.email,
        total=meta.total,
        page=page,
    )

    return AuditLogListResponse(items=items, pagination=meta)


# -- GET /admin/audit-log/export ----------------------------------------------


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export audit log entries as CSV",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def export_audit_log(
    user=Security(get_current_user, scopes=["audit:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    # -- Filters (same as list endpoint) --------------------------------------
    action: AuditAction | None = Query(
        default=None, description="Filter by audit action type."
    ),
    actor_id: uuid.UUID | None = Query(
        default=None, description="Filter by the acting user's ID."
    ),
    actor_type: str | None = Query(
        default=None, description="Filter by actor type (user, reporter, system)."
    ),
    resource_type: str | None = Query(
        default=None,
        description="Filter by resource type (report, user, tenant, etc.).",
    ),
    resource_id: str | None = Query(
        default=None, description="Filter by specific resource ID."
    ),
    date_from: datetime | None = Query(
        default=None, description="Filter entries created on or after this date."
    ),
    date_to: datetime | None = Query(
        default=None, description="Filter entries created on or before this date."
    ),
) -> StreamingResponse:
    """Export filtered audit log entries as a CSV file.

    Returns a downloadable CSV file containing audit log entries
    matching the specified filters.  The export is limited to 10,000
    entries to prevent excessive memory usage.

    This supports the compliance requirement for audit log export
    (e.g. for external auditors or regulatory submissions).

    Requires ``audit:read`` scope (AUDITOR, TENANT_ADMIN, SYSTEM_ADMIN).
    """
    # Fetch up to 10,000 entries for export
    audit_repo = AuditRepository(db)

    max_export_rows = 10_000
    all_entries: list = []
    current_page = 1

    while len(all_entries) < max_export_rows:
        page_params = PaginationParams(page=current_page, page_size=100)
        entries, meta = await audit_repo.list_paginated(
            pagination=page_params,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            resource_type=resource_type,
            resource_id=resource_id,
            date_from=date_from,
            date_to=date_to,
        )
        all_entries.extend(entries)

        if current_page >= meta.total_pages:
            break
        current_page += 1

    # Trim to max export rows
    all_entries = all_entries[:max_export_rows]

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "action",
        "actor_id",
        "actor_type",
        "resource_type",
        "resource_id",
        "details",
        "ip_address",
        "created_at",
    ])

    for entry in all_entries:
        writer.writerow([
            str(entry.id),
            entry.action.value,
            str(entry.actor_id) if entry.actor_id else "",
            entry.actor_type,
            entry.resource_type,
            entry.resource_id,
            str(entry.details) if entry.details else "",
            entry.ip_address or "",
            entry.created_at.isoformat(),
        ])

    logger.info(
        "admin_audit_log_exported",
        user_email=user.email,
        entry_count=len(all_entries),
    )

    csv_content = output.getvalue()
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=audit-log-export.csv",
        },
    )
