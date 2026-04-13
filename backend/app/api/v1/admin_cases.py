"""Hinweisgebersystem – Admin Case Management API Endpoints.

Provides:
- **GET /admin/cases** — Paginated case list with filters, search,
  sorting, and deadline highlighting for overdue cases.
- **GET /admin/cases/{case_id}** — Full case detail including messages
  and audit trail.
- **PATCH /admin/cases/{case_id}** — Update case status, priority,
  assignment, category, or sub-status with optimistic locking.
  When the main status changes without an explicit ``sub_status_id``,
  the sub-status is automatically cleared.
- **POST /admin/cases/{case_id}/messages** — Send a message to the
  reporter visible in the anonymous mailbox.
- **POST /admin/cases/{case_id}/notes** — Create an internal note
  visible only to handlers.
- **GET /admin/cases/{case_id}/audit** — Audit trail for a specific
  case.
- **POST /admin/cases/{case_id}/labels** — Assign a label to a case.
- **DELETE /admin/cases/{case_id}/labels/{label_id}** — Remove a
  label from a case.

All endpoints require OIDC-authenticated admin users with appropriate
scopes.  Tenant isolation is enforced via Row-Level Security (RLS).

Usage::

    from app.api.v1.admin_cases import router as admin_cases_router
    api_v1_router.include_router(admin_cases_router)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.audit_log import AuditAction
from app.models.report import Channel, Priority, ReportStatus
from app.repositories.audit_repo import AuditRepository
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.message import MessageCreateHandler, MessageResponse
from app.schemas.report import ReportResponse, ReportUpdate
from app.services.message_service import MessageService
from app.services.report_service import ReportService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/cases", tags=["admin-cases"])


# ── Response schemas ─────────────────────────────────────────
# Inline schemas for audit log entries and the enriched case
# detail response.  These are specific to the admin case
# endpoints and don't warrant separate schema files.


from pydantic import BaseModel, ConfigDict, Field  # noqa: E402


class AuditLogEntry(BaseModel):
    """Audit log entry for the case detail timeline."""

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


class CaseDetailResponse(ReportResponse):
    """Extended case response with messages and audit trail."""

    messages: list[MessageResponse] = Field(
        default_factory=list,
        description="All messages including internal notes.",
    )
    audit_trail: list[AuditLogEntry] = Field(
        default_factory=list,
        description="Chronological audit trail for this case.",
    )
    unread_count: int = Field(
        default=0,
        description="Number of unread reporter messages.",
    )
    is_overdue_confirmation: bool = Field(
        default=False,
        description="Whether the 7-day confirmation deadline has passed.",
    )
    is_overdue_feedback: bool = Field(
        default=False,
        description="Whether the 3-month feedback deadline has passed.",
    )


class CaseListItem(ReportResponse):
    """Case list item with deadline highlighting."""

    unread_count: int = Field(
        default=0,
        description="Number of unread reporter messages.",
    )
    is_overdue_confirmation: bool = Field(
        default=False,
        description="Whether the 7-day confirmation deadline has passed.",
    )
    is_overdue_feedback: bool = Field(
        default=False,
        description="Whether the 3-month feedback deadline has passed.",
    )


class CaseListResponse(PaginatedResponse[CaseListItem]):
    """Paginated list of cases for the admin dashboard."""

    pass


# ── Helpers ──────────────────────────────────────────────────


def _check_deadline_overdue(
    deadline: datetime | None,
    sent_at: datetime | None,
) -> bool:
    """Check if a deadline has passed and the action was not taken.

    Parameters
    ----------
    deadline:
        The deadline timestamp.
    sent_at:
        When the deadline action was fulfilled (e.g. confirmation sent).

    Returns
    -------
    bool
        ``True`` if the deadline is overdue.
    """
    if deadline is None:
        return False
    if sent_at is not None:
        return False
    return datetime.now(UTC) > deadline


# ── GET /admin/cases ─────────────────────────────────────────


@router.get(
    "",
    response_model=CaseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List cases with filters, search, and sorting",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_cases(
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    # ── Pagination ───────────────────────────────────────────
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)."
    ),
    # ── Filters ──────────────────────────────────────────────
    status_filter: ReportStatus | None = Query(
        default=None, alias="status", description="Filter by case status."
    ),
    priority: Priority | None = Query(
        default=None, description="Filter by priority."
    ),
    channel: Channel | None = Query(
        default=None, description="Filter by reporting channel."
    ),
    category: str | None = Query(
        default=None, description="Filter by category key."
    ),
    assigned_to: uuid.UUID | None = Query(
        default=None, description="Filter by assigned handler."
    ),
    search: str | None = Query(
        default=None,
        max_length=500,
        description="Full-text search query (German tsvector).",
    ),
    date_from: datetime | None = Query(
        default=None, description="Filter reports created on or after this date."
    ),
    date_to: datetime | None = Query(
        default=None, description="Filter reports created on or before this date."
    ),
    overdue_only: bool = Query(
        default=False, description="Show only cases with overdue deadlines."
    ),
    # ── Sorting ──────────────────────────────────────────────
    sort_by: str = Query(
        default="created_at",
        description="Field to sort by (e.g. created_at, status, priority).",
    ),
    sort_desc: bool = Query(
        default=True,
        description="Sort descending (newest first).",
    ),
) -> CaseListResponse:
    """List all cases with filtering, search, sorting, and pagination.

    Supports full-text search with German stemming, filtering by status,
    priority, channel, category, assignment, and date range.  Overdue
    deadline highlighting is included for each case.

    Requires ``cases:read`` scope (HANDLER, TENANT_ADMIN, SYSTEM_ADMIN,
    REVIEWER, AUDITOR).
    """
    pagination = PaginationParams(page=page, page_size=page_size)
    report_service = ReportService(db, tenant_id)
    message_service = MessageService(db, tenant_id)

    reports, meta = await report_service.list_reports(
        pagination=pagination,
        status=status_filter,
        priority=priority,
        channel=channel,
        category=category,
        assigned_to=assigned_to,
        search=search,
        date_from=date_from,
        date_to=date_to,
        overdue_only=overdue_only,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )

    # Enrich each report with deadline and unread info
    items: list[CaseListItem] = []
    for report in reports:
        unread_count = await message_service.count_unread_for_handler(report.id)

        item_data = CaseListItem.model_validate(report)
        item_data.unread_count = unread_count
        item_data.is_overdue_confirmation = _check_deadline_overdue(
            report.confirmation_deadline,
            report.confirmation_sent_at,
        )
        item_data.is_overdue_feedback = _check_deadline_overdue(
            report.feedback_deadline,
            report.feedback_sent_at,
        )
        items.append(item_data)

    logger.info(
        "admin_cases_listed",
        user_email=user.email,
        total=meta.total,
        page=page,
    )

    return CaseListResponse(items=items, pagination=meta)


# ── GET /admin/cases/{case_id} ───────────────────────────────


@router.get(
    "/{case_id}",
    response_model=CaseDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full case detail with messages and audit trail",
    responses={
        404: {"description": "Case not found"},
    },
)
async def get_case_detail(
    case_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> CaseDetailResponse:
    """Get full case detail including all messages and audit trail.

    Returns the complete case record with decrypted fields, all
    messages (including internal handler notes), and the chronological
    audit trail.  Automatically marks all unread reporter messages
    as read.

    Requires ``cases:read`` scope.
    """
    report_service = ReportService(db, tenant_id)
    message_service = MessageService(db, tenant_id)
    audit_repo = AuditRepository(db)

    # Fetch the report
    report = await report_service.get_report_by_id(
        case_id,
        with_messages=True,
        with_attachments=True,
    )

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    # Mark all reporter messages as read (handler opened the case)
    await message_service.mark_all_reporter_messages_read(case_id)

    # Fetch messages with full detail (includes internal notes)
    messages = await message_service.list_messages_for_admin(
        case_id,
        with_attachments=True,
    )
    message_responses = [
        MessageResponse.model_validate(msg) for msg in messages
    ]

    # Fetch audit trail for this case
    audit_entries = await audit_repo.list_by_resource(
        resource_type="report",
        resource_id=str(case_id),
    )
    audit_trail = [
        AuditLogEntry.model_validate(entry) for entry in audit_entries
    ]

    # Unread count (after marking as read, this will be 0 for reporter
    # messages but may still count new ones arriving concurrently)
    unread_count = await message_service.count_unread_for_handler(case_id)

    # Build enriched response
    response = CaseDetailResponse.model_validate(report)
    response.messages = message_responses
    response.audit_trail = audit_trail
    response.unread_count = unread_count
    response.is_overdue_confirmation = _check_deadline_overdue(
        report.confirmation_deadline,
        report.confirmation_sent_at,
    )
    response.is_overdue_feedback = _check_deadline_overdue(
        report.feedback_deadline,
        report.feedback_sent_at,
    )

    logger.info(
        "admin_case_viewed",
        case_id=str(case_id),
        user_email=user.email,
    )

    return response


# ── PATCH /admin/cases/{case_id} ─────────────────────────────


@router.patch(
    "/{case_id}",
    response_model=ReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Update case status, priority, or assignment",
    responses={
        404: {"description": "Case not found"},
        409: {"description": "Optimistic locking conflict"},
        422: {"description": "Invalid status transition"},
    },
)
async def update_case(
    case_id: uuid.UUID,
    body: ReportUpdate,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> ReportResponse:
    """Update case metadata with optimistic locking.

    Supports updating status (with workflow validation), priority,
    handler assignment, category, sub-status, and related case
    numbers.  The ``version`` field must match the current database
    version to prevent concurrent edit conflicts.

    When the main status changes and no ``sub_status_id`` is
    provided, the sub-status is automatically cleared (it belonged
    to the previous status).  An explicit ``sub_status_id`` always
    takes precedence.

    Status transitions are validated against the HinSchG workflow:
    ``eingegangen → in_pruefung → in_bearbeitung ↔ rueckmeldung → abgeschlossen``

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN, SYSTEM_ADMIN).
    """
    report_service = ReportService(db, tenant_id)

    try:
        updated = await report_service.update_report(
            case_id,
            body,
            actor_id=user.id,
        )
    except ValueError as exc:
        # Invalid status transition
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    if updated is None:
        # Could be not found or optimistic locking conflict.
        # Check whether the case exists to differentiate.
        existing = await report_service.get_report_by_id(case_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found.",
            )
        # Case exists but version mismatch
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Optimistic locking conflict. The case was modified by "
                "another user. Please reload and try again."
            ),
        )

    logger.info(
        "admin_case_updated",
        case_id=str(case_id),
        user_email=user.email,
        changes={
            k: v
            for k, v in body.model_dump(exclude_none=True, exclude={"version"}).items()
            if v is not None
        },
    )

    return ReportResponse.model_validate(updated)


# ── POST /admin/cases/{case_id}/messages ─────────────────────


@router.post(
    "/{case_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message to the reporter",
    responses={
        404: {"description": "Case not found"},
    },
)
async def send_message_to_reporter(
    case_id: uuid.UUID,
    body: MessageCreateHandler,
    user=Security(get_current_user, scopes=["messages:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> MessageResponse:
    """Send a message to the reporter visible in the anonymous mailbox.

    The message content is encrypted at the ORM level via pgcrypto.
    This endpoint creates messages with ``is_internal=False`` —
    the message will be visible to the reporter in their mailbox.

    For internal notes (handler-only), use the ``/notes`` endpoint.

    Requires ``messages:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    # Verify the case exists
    report_service = ReportService(db, tenant_id)
    report = await report_service.get_report_by_id(case_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    message_service = MessageService(db, tenant_id)
    message = await message_service.create_handler_message(
        report_id=case_id,
        content=body.content,
        sender_user_id=user.id,
        is_internal=False,  # Always non-internal for this endpoint
    )

    logger.info(
        "admin_message_sent",
        case_id=str(case_id),
        message_id=str(message.id),
        user_email=user.email,
    )

    return MessageResponse.model_validate(message)


# ── POST /admin/cases/{case_id}/notes ────────────────────────


@router.post(
    "/{case_id}/notes",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an internal note",
    responses={
        404: {"description": "Case not found"},
    },
)
async def create_internal_note(
    case_id: uuid.UUID,
    body: MessageCreateHandler,
    user=Security(get_current_user, scopes=["notes:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> MessageResponse:
    """Create an internal note visible only to handlers.

    Internal notes are never shown to the reporter in the anonymous
    mailbox.  They are used for handler-to-handler communication,
    investigation notes, and compliance documentation.

    The note content is encrypted at the ORM level via pgcrypto.

    Requires ``notes:write`` scope (HANDLER, TENANT_ADMIN, SYSTEM_ADMIN).
    """
    # Verify the case exists
    report_service = ReportService(db, tenant_id)
    report = await report_service.get_report_by_id(case_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    message_service = MessageService(db, tenant_id)
    message = await message_service.create_handler_message(
        report_id=case_id,
        content=body.content,
        sender_user_id=user.id,
        is_internal=True,  # Always internal for this endpoint
    )

    logger.info(
        "admin_note_created",
        case_id=str(case_id),
        message_id=str(message.id),
        user_email=user.email,
    )

    return MessageResponse.model_validate(message)


# ── GET /admin/cases/{case_id}/audit ─────────────────────────


@router.get(
    "/{case_id}/audit",
    response_model=list[AuditLogEntry],
    status_code=status.HTTP_200_OK,
    summary="Get audit trail for a case",
    responses={
        404: {"description": "Case not found"},
    },
)
async def get_case_audit_trail(
    case_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> list[AuditLogEntry]:
    """Get the chronological audit trail for a specific case.

    Returns all audit log entries associated with the given case,
    ordered from oldest to newest.  This provides a complete timeline
    of all actions taken on the case including status changes, handler
    assignments, messages sent, and identity disclosure events.

    Requires ``cases:read`` scope.
    """
    # Verify the case exists
    report_service = ReportService(db, tenant_id)
    report = await report_service.get_report_by_id(case_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    audit_repo = AuditRepository(db)
    entries = await audit_repo.list_by_resource(
        resource_type="report",
        resource_id=str(case_id),
    )

    logger.info(
        "admin_case_audit_viewed",
        case_id=str(case_id),
        user_email=user.email,
        entry_count=len(entries),
    )

    return [AuditLogEntry.model_validate(entry) for entry in entries]


# ── POST /admin/cases/{case_id}/labels ─────────────────────


@router.post(
    "/{case_id}/labels",
    response_model=list["LabelSummary"],
    status_code=status.HTTP_200_OK,
    summary="Assign a label to a case",
    responses={
        404: {"description": "Case or label not found"},
        409: {"description": "Label already assigned"},
    },
)
async def assign_label_to_case(
    case_id: uuid.UUID,
    body: "LabelAssignment",
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> list["LabelSummary"]:
    """Assign a label to a case.

    The label must belong to the same tenant and be active.
    Returns the updated list of labels assigned to the case.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    from sqlalchemy import select

    from app.models.label import Label
    from app.schemas.label import LabelAssignment, LabelSummary

    report_service = ReportService(db, tenant_id)
    report = await report_service.get_report_by_id(case_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    # Verify the label exists and belongs to the same tenant
    label_stmt = select(Label).where(
        Label.id == body.label_id,
        Label.tenant_id == tenant_id,
    )
    label_result = await db.execute(label_stmt)
    label = label_result.scalar_one_or_none()

    if label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found.",
        )

    if not label.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot assign an inactive label.",
        )

    # Check if already assigned
    if label in report.labels:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Label is already assigned to this case.",
        )

    report.labels.append(label)
    await db.flush()

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.LABEL_ASSIGNED,
        resource_type="report",
        resource_id=str(case_id),
        actor_id=user.id,
        actor_type="user",
        details={"label_id": str(label.id), "label_name": label.name},
    )

    await db.commit()
    await db.refresh(report)

    logger.info(
        "admin_label_assigned",
        case_id=str(case_id),
        label_id=str(label.id),
        label_name=label.name,
        user_email=user.email,
    )

    return [LabelSummary.model_validate(lbl) for lbl in report.labels]


# ── DELETE /admin/cases/{case_id}/labels/{label_id} ──────────


@router.delete(
    "/{case_id}/labels/{label_id}",
    response_model=list["LabelSummary"],
    status_code=status.HTTP_200_OK,
    summary="Remove a label from a case",
    responses={
        404: {"description": "Case or label assignment not found"},
    },
)
async def remove_label_from_case(
    case_id: uuid.UUID,
    label_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> list["LabelSummary"]:
    """Remove a label from a case.

    Returns the updated list of labels assigned to the case.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    from sqlalchemy import select

    from app.models.label import Label
    from app.schemas.label import LabelSummary

    report_service = ReportService(db, tenant_id)
    report = await report_service.get_report_by_id(case_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    # Find the label in the case's current labels
    target_label = None
    for lbl in report.labels:
        if lbl.id == label_id:
            target_label = lbl
            break

    if target_label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label is not assigned to this case.",
        )

    report.labels.remove(target_label)
    await db.flush()

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.LABEL_REMOVED,
        resource_type="report",
        resource_id=str(case_id),
        actor_id=user.id,
        actor_type="user",
        details={
            "label_id": str(target_label.id),
            "label_name": target_label.name,
        },
    )

    await db.commit()
    await db.refresh(report)

    logger.info(
        "admin_label_removed",
        case_id=str(case_id),
        label_id=str(label_id),
        label_name=target_label.name,
        user_email=user.email,
    )

    return [LabelSummary.model_validate(lbl) for lbl in report.labels]
