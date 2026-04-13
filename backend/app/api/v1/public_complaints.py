"""Hinweisgebersystem -- Public LkSG Complaints API Endpoints.

Provides:
- **POST /public/complaints** -- Submit a public LkSG supply chain
  complaint with extended fields (country, organization, supply chain
  tier, LkSG category, reporter relationship).
- **POST /public/complaints/verify** -- Authenticate with case number +
  passphrase/password for mailbox access.
- **GET /public/complaints/mailbox/status** -- Get complaint status.
- **GET /public/complaints/mailbox/messages** -- List mailbox messages.
- **POST /public/complaints/mailbox/messages** -- Send a reporter
  message.

The LkSG (Supply Chain Due Diligence Act) channel is publicly accessible
for reporting human rights and environmental violations in corporate
supply chains.  It uses the same mailbox infrastructure as HinSchG
reports but enforces the ``lksg`` channel type, requires LkSG-specific
extended fields, and applies a 7-year retention period (vs. 3 years
for HinSchG).

The public complaints endpoint is accessible without prior tenant-
specific authentication -- the tenant is resolved from the subdomain
or path prefix by the tenant resolver middleware.

Usage::

    from app.api.v1.public_complaints import router as complaints_router
    api_v1_router.include_router(complaints_router)
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.reports import (
    MailboxSession,
    create_mailbox_session_token,
    get_mailbox_session,
    set_reporter_session_cookie,
    verify_hcaptcha,
)
from app.core.config import Settings, get_settings
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.report import Channel
from app.schemas.auth import MailboxLoginRequest, MailboxLoginResponse
from app.schemas.message import MessageCreate, MessageMailboxResponse
from app.schemas.report import (
    ReportCreate,
    ReportCreateResponse,
    ReportMailboxResponse,
)
from app.services.message_service import MessageService
from app.services.report_service import ReportService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/public/complaints", tags=["complaints"])


# ── POST /public/complaints ─────────────────────────────────


@router.post(
    "",
    response_model=ReportCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a public LkSG supply chain complaint",
    responses={
        400: {"description": "hCaptcha verification failed or missing LkSG fields"},
        422: {"description": "Validation error"},
    },
)
async def create_complaint(
    body: ReportCreate,
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReportCreateResponse:
    """Submit a new public LkSG supply chain complaint.

    The LkSG channel requires extended fields beyond the standard
    HinSchG report:

    - ``country``: ISO 3166-1 alpha-3 country code where the violation
      occurred.
    - ``organization``: name of the reported organisation.
    - ``lksg_category``: type of violation (child labour, forced labour,
      environmental damage, etc.).
    - ``reporter_relationship``: reporter's relationship to the
      organisation (employee, supplier, NGO, etc.).
    - ``supply_chain_tier``: whether the violation is in own operations,
      direct supplier, or indirect supplier.

    An hCaptcha token is required for bot protection.  The channel
    is forced to ``lksg`` regardless of the request body value.

    On success returns a 16-character case number and passphrase.
    The 7-year retention period is automatically applied.
    """
    # hCaptcha verification.
    is_valid_captcha = await verify_hcaptcha(body.captcha_token, settings)
    if not is_valid_captcha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hCaptcha verification failed. Please try again.",
        )

    # Force LkSG channel.
    body.channel = Channel.LKSG

    # Validate LkSG-required fields.
    if not body.lksg_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LkSG category is required for supply chain complaints.",
        )
    if not body.country:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Country is required for LkSG supply chain complaints.",
        )
    if not body.organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is required for LkSG supply chain complaints.",
        )

    service = ReportService(db, tenant_id)
    result = await service.create_report(body)

    # Issue a short-lived session token for immediate file upload.
    session_token, _ = create_mailbox_session_token(
        report_id=uuid.UUID(result.report_id),
        case_number=result.case_number,
        tenant_id=tenant_id,
        settings=settings,
    )

    logger.info(
        "lksg_complaint_submitted",
        case_number=result.case_number,
        channel="lksg",
        country=body.country,
        is_anonymous=body.is_anonymous,
    )

    return ReportCreateResponse(
        case_number=result.case_number,
        report_id=result.report_id,
        passphrase=result.passphrase,
        access_token=session_token,
        message=result.message,
    )


# ── POST /public/complaints/verify ──────────────────────────


@router.post(
    "/verify",
    response_model=MailboxLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate for LkSG complaint mailbox",
    responses={
        401: {"description": "Invalid credentials"},
    },
)
async def verify_complaint(
    body: MailboxLoginRequest,
    response: Response,
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MailboxLoginResponse:
    """Authenticate with case number and passphrase/password.

    Returns a JWT session token for the LkSG complaint mailbox.
    Only reports submitted through the LkSG channel can be accessed
    via this endpoint -- HinSchG reports should use ``/reports/verify``.

    Uses constant-time bcrypt comparison to prevent timing attacks.
    Returns a generic error for invalid credentials to prevent
    enumeration of case numbers.
    """
    service = ReportService(db, tenant_id)
    report = await service.authenticate_mailbox(
        case_number=body.case_number,
        credential=body.passphrase,
    )

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid case number or passphrase.",
        )

    # Verify this is an LkSG report.
    if report.channel != Channel.LKSG:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid case number or passphrase.",
        )

    # Create mailbox session token.
    session_token, expires_at = create_mailbox_session_token(
        report_id=report.id,
        case_number=report.case_number,
        tenant_id=tenant_id,
        settings=settings,
    )

    # Set httpOnly session cookie.
    set_reporter_session_cookie(response, session_token)

    logger.info(
        "lksg_mailbox_authenticated",
        case_number=report.case_number,
    )

    return MailboxLoginResponse(
        access_token=session_token,
        expires_at=expires_at,
        case_number=report.case_number,
        channel=report.channel,
        status=report.status,
    )


# ── GET /public/complaints/mailbox/status ────────────────────


@router.get(
    "/mailbox/status",
    response_model=ReportMailboxResponse,
    status_code=status.HTTP_200_OK,
    summary="Get LkSG complaint status",
)
async def get_complaint_status(
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ReportMailboxResponse:
    """Get current complaint status and metadata for the LkSG mailbox.

    Returns limited information suitable for the reporter view --
    excludes internal-only fields like priority and handler assignment.
    Includes LkSG-specific fields (country, organization, lksg_category).
    """
    service = ReportService(db, session.tenant_id)
    report = await service.get_report_by_id(session.report_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    return ReportMailboxResponse.model_validate(report)


# ── GET /public/complaints/mailbox/messages ──────────────────


@router.get(
    "/mailbox/messages",
    response_model=list[MessageMailboxResponse],
    status_code=status.HTTP_200_OK,
    summary="List LkSG complaint mailbox messages",
)
async def list_complaint_messages(
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[MessageMailboxResponse]:
    """List all messages visible to the LkSG complainant.

    Excludes internal handler notes to prevent information leakage.
    Messages are returned in chronological order.  Automatically
    marks all unread handler/system messages as read when the
    complainant opens the mailbox.
    """
    service = MessageService(db, session.tenant_id)

    # Mark handler/system messages as read (complainant opened mailbox).
    await service.mark_all_handler_messages_read(session.report_id)

    # Fetch mailbox-visible messages (excludes internal notes).
    messages = await service.list_messages_for_mailbox(session.report_id)

    return [MessageMailboxResponse.model_validate(msg) for msg in messages]


# ── POST /public/complaints/mailbox/messages ─────────────────


@router.post(
    "/mailbox/messages",
    response_model=MessageMailboxResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message in LkSG complaint mailbox",
)
async def send_complaint_message(
    body: MessageCreate,
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MessageMailboxResponse:
    """Send a message from the complainant in the LkSG mailbox.

    The message content is encrypted at the ORM level via pgcrypto.
    The sender is always identified as ``REPORTER`` with no user ID
    to preserve anonymity.
    """
    service = MessageService(db, session.tenant_id)
    message = await service.create_reporter_message(
        report_id=session.report_id,
        content=body.content,
    )

    return MessageMailboxResponse.model_validate(message)
