"""Hinweisgebersystem -- Public Reporter API Endpoints.

Provides:
- **POST /reports** -- Submit a new HinSchG report with hCaptcha
  verification.  Returns a case number and system-generated passphrase.
- **POST /reports/verify** -- Authenticate with case number +
  passphrase/password.  Returns a JWT session token for mailbox access.
- **GET /reports/mailbox/status** -- Get report status and metadata.
- **GET /reports/mailbox/messages** -- List mailbox messages (excludes
  internal handler notes).
- **POST /reports/mailbox/messages** -- Send a reporter message.
- **POST /reports/mailbox/messages/{message_id}/attachments** -- Upload
  a file attachment to a specific message.
- **GET /reports/mailbox/attachments/{attachment_id}** -- Download a
  file attachment (decrypted).

All ``/mailbox/*`` endpoints require the JWT session token from the
``/verify`` endpoint, passed via ``Authorization: Bearer`` header or
the ``reporter_session`` httpOnly cookie.

Anonymous reporters are never tracked by IP, cookies, or other
identifying metadata -- this is enforced by the anonymity middleware.

Usage::

    from app.api.v1.reports import router as reports_router
    api_v1_router.include_router(reports_router)
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import jwt as pyjwt
import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.report import Channel
from app.models.tenant import Tenant
from app.schemas.auth import MailboxLoginRequest, MailboxLoginResponse
from app.schemas.message import MessageCreate, MessageMailboxResponse
from app.schemas.report import (
    AttachmentSummary,
    ReportCreate,
    ReportCreateResponse,
    ReportMailboxResponse,
)
from app.services.file_service import FileService
from app.services.message_service import MessageService
from app.services.report_service import ReportService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

# ── hCaptcha verification ────────────────────────────────────
# Server-side verification of the hCaptcha response token.
# In development the hCaptcha test keys (starting with ``0x``)
# bypass external calls.

_HCAPTCHA_VERIFY_URL = "https://api.hcaptcha.com/siteverify"


async def verify_hcaptcha(
    token: str | None,
    settings: Settings,
) -> bool:
    """Verify an hCaptcha response token with the hCaptcha API.

    Parameters
    ----------
    token:
        The hCaptcha response token from the frontend widget.
    settings:
        Application settings (for the hCaptcha secret key).

    Returns
    -------
    bool
        ``True`` if verification succeeds or is bypassed in dev mode.
    """
    if not token:
        return False

    # Development bypass: hCaptcha test keys start with "0x".
    if settings.hcaptcha_secret.startswith("0x"):
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _HCAPTCHA_VERIFY_URL,
                data={
                    "secret": settings.hcaptcha_secret,
                    "response": token,
                },
            )
            result = resp.json()
            return result.get("success", False)
    except Exception:
        logger.warning("hcaptcha_verification_failed", exc_info=True)
        return False


# ── Mailbox session JWT helpers ──────────────────────────────
# After successful passphrase/password verification the reporter
# receives a short-lived JWT for mailbox access.  The token is
# delivered both in the response body and as an httpOnly cookie.

_SESSION_COOKIE_NAME = "reporter_session"
_SESSION_EXPIRE_HOURS = 4  # Short-lived for anonymous mailbox


def create_mailbox_session_token(
    *,
    report_id: uuid.UUID,
    case_number: str,
    tenant_id: uuid.UUID,
    settings: Settings,
) -> tuple[str, datetime]:
    """Create a short-lived JWT for anonymous mailbox access.

    Parameters
    ----------
    report_id:
        UUID of the authenticated report.
    case_number:
        The 16-character case identifier.
    tenant_id:
        UUID of the tenant.
    settings:
        Application settings (for JWT signing key).

    Returns
    -------
    tuple[str, datetime]
        ``(encoded_token, expires_at)``
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=_SESSION_EXPIRE_HOURS)
    payload = {
        "sub": "anonymous",
        "report_id": str(report_id),
        "case_number": case_number,
        "tenant_id": str(tenant_id),
        "type": "reporter_session",
        "iat": now,
        "exp": expires_at,
    }
    token = pyjwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def set_reporter_session_cookie(
    response: Response,
    token: str,
    *,
    max_age: int = _SESSION_EXPIRE_HOURS * 3600,
) -> None:
    """Set the mailbox session JWT as an httpOnly cookie.

    Parameters
    ----------
    response:
        FastAPI ``Response`` object.
    token:
        Encoded JWT string.
    max_age:
        Cookie max-age in seconds.
    """
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/api",
    )


# ── Mailbox session dependency ───────────────────────────────
# Extracts and validates the JWT from the Authorization header or
# the reporter_session cookie.  Used by all /mailbox/* endpoints.


class MailboxSession:
    """Parsed mailbox session claims.

    Attributes
    ----------
    report_id:
        UUID of the authenticated report.
    case_number:
        The 16-character case identifier.
    tenant_id:
        UUID of the tenant (from the JWT payload).
    """

    __slots__ = ("report_id", "case_number", "tenant_id")

    def __init__(
        self,
        report_id: uuid.UUID,
        case_number: str,
        tenant_id: uuid.UUID,
    ) -> None:
        self.report_id = report_id
        self.case_number = case_number
        self.tenant_id = tenant_id


async def get_mailbox_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MailboxSession:
    """FastAPI dependency that extracts the mailbox session from JWT.

    Reads the token from the ``Authorization: Bearer`` header or
    the ``reporter_session`` httpOnly cookie.

    Raises
    ------
    HTTPException (401)
        If no valid session is found or the token is expired/invalid.
    """
    token: str | None = None

    # 1. Try Authorization header.
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:]

    # 2. Fall back to session cookie.
    if not token:
        token = request.cookies.get(_SESSION_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mailbox session required. Please authenticate first.",
        )

    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please authenticate again.",
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )

    if payload.get("type") != "reporter_session":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session type.",
        )

    try:
        return MailboxSession(
            report_id=uuid.UUID(payload["report_id"]),
            case_number=payload["case_number"],
            tenant_id=uuid.UUID(payload["tenant_id"]),
        )
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session token.",
        )


# ── Tenant DEK helper ────────────────────────────────────────


async def _get_tenant_dek_ciphertext(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> bytes:
    """Fetch the tenant's DEK ciphertext for file encryption.

    Parameters
    ----------
    db:
        Database session.
    tenant_id:
        UUID of the tenant.

    Returns
    -------
    bytes
        The DEK ciphertext as bytes.

    Raises
    ------
    HTTPException (500)
        If the tenant cannot be found.
    """
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant configuration error.",
        )

    dek = tenant.dek_ciphertext
    return dek.encode() if isinstance(dek, str) else dek


# ── POST /reports ────────────────────────────────────────────


@router.post(
    "",
    response_model=ReportCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new HinSchG report",
    responses={
        400: {"description": "hCaptcha verification failed"},
        422: {"description": "Validation error"},
    },
)
async def create_report(
    body: ReportCreate,
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReportCreateResponse:
    """Submit a new whistleblower report (HinSchG channel).

    The reporter provides a subject, description, optional category,
    and optional identity (name/email/phone for non-anonymous reports).
    An hCaptcha token is required for bot protection.

    On success, the response contains a 16-character case number and
    a 6-word passphrase (or confirmation that a self-chosen password
    was accepted).  The passphrase is only shown once -- the reporter
    must save it to access their anonymous mailbox.
    """
    # hCaptcha verification.
    is_valid_captcha = await verify_hcaptcha(body.captcha_token, settings)
    if not is_valid_captcha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hCaptcha verification failed. Please try again.",
        )

    # Force HinSchG channel for this endpoint.
    body.channel = Channel.HINSCHG

    service = ReportService(db, tenant_id)
    result = await service.create_report(body)

    # Issue a short-lived session token so the frontend can
    # upload file attachments immediately after submission.
    session_token, _ = create_mailbox_session_token(
        report_id=uuid.UUID(result.report_id),
        case_number=result.case_number,
        tenant_id=tenant_id,
        settings=settings,
    )

    logger.info(
        "report_submitted",
        case_number=result.case_number,
        channel="hinschg",
        is_anonymous=body.is_anonymous,
    )

    return ReportCreateResponse(
        case_number=result.case_number,
        report_id=result.report_id,
        passphrase=result.passphrase,
        access_token=session_token,
        message=result.message,
    )


# ── POST /reports/verify ─────────────────────────────────────


@router.post(
    "/verify",
    response_model=MailboxLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate for mailbox access",
    responses={
        401: {"description": "Invalid credentials"},
    },
)
async def verify_report(
    body: MailboxLoginRequest,
    response: Response,
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MailboxLoginResponse:
    """Authenticate with case number and passphrase/password.

    Returns a JWT session token for mailbox API access.  The token
    is also set as an httpOnly cookie.

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
        "mailbox_authenticated",
        case_number=report.case_number,
    )

    return MailboxLoginResponse(
        access_token=session_token,
        expires_at=expires_at,
        case_number=report.case_number,
        channel=report.channel,
        status=report.status,
    )


# ── GET /reports/mailbox/status ──────────────────────────────


@router.get(
    "/mailbox/status",
    response_model=ReportMailboxResponse,
    status_code=status.HTTP_200_OK,
    summary="Get report status for mailbox",
)
async def get_mailbox_status(
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ReportMailboxResponse:
    """Get the current report status and metadata for the mailbox UI.

    Returns limited information suitable for the reporter view --
    excludes internal-only fields like priority and handler assignment.
    """
    service = ReportService(db, session.tenant_id)
    report = await service.get_report_by_id(session.report_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found.",
        )

    return ReportMailboxResponse.model_validate(report)


# ── GET /reports/mailbox/messages ────────────────────────────


@router.get(
    "/mailbox/messages",
    response_model=list[MessageMailboxResponse],
    status_code=status.HTTP_200_OK,
    summary="List mailbox messages",
)
async def list_mailbox_messages(
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[MessageMailboxResponse]:
    """List all messages visible to the reporter.

    Excludes internal handler notes to prevent information leakage.
    Messages are returned in chronological order.  Automatically
    marks all unread handler/system messages as read.
    """
    service = MessageService(db, session.tenant_id)

    # Mark handler/system messages as read (reporter opened mailbox).
    await service.mark_all_handler_messages_read(session.report_id)

    # Fetch mailbox-visible messages (excludes internal notes).
    messages = await service.list_messages_for_mailbox(session.report_id)

    return [MessageMailboxResponse.model_validate(msg) for msg in messages]


# ── POST /reports/mailbox/messages ───────────────────────────


@router.post(
    "/mailbox/messages",
    response_model=MessageMailboxResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a reporter message",
)
async def send_mailbox_message(
    body: MessageCreate,
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MessageMailboxResponse:
    """Send a message from the reporter in the anonymous mailbox.

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


# ── POST /reports/mailbox/messages/{message_id}/attachments ──


@router.post(
    "/mailbox/messages/{message_id}/attachments",
    response_model=AttachmentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attachment to a message",
    responses={
        400: {"description": "File validation failed"},
        404: {"description": "Message not found"},
    },
)
async def upload_attachment(
    message_id: uuid.UUID,
    file: UploadFile,
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AttachmentSummary:
    """Upload a file attachment to a specific message.

    Files are encrypted with AES-256-GCM before upload to MinIO.
    Maximum file size is 50 MB, maximum 10 files per message.

    The file's per-file encryption key is itself envelope-encrypted
    with the tenant DEK for secure storage.
    """
    # Verify the message belongs to this report.
    msg_service = MessageService(db, session.tenant_id)
    message = await msg_service.get_message_by_id(message_id)

    if message is None or message.report_id != session.report_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )

    # Read file data.
    data = await file.read()

    # Fetch tenant DEK ciphertext for envelope encryption.
    dek_ciphertext = await _get_tenant_dek_ciphertext(db, session.tenant_id)

    file_service = FileService(
        db,
        session.tenant_id,
        settings.encryption_master_key,
    )

    # Validate upload constraints (size + per-message file count).
    try:
        await file_service.validate_upload(
            file_size=len(data),
            message_id=message_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Encrypt and upload the file.
    try:
        attachment = await file_service.upload_file(
            report_id=session.report_id,
            filename=file.filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            tenant_dek_ciphertext=dek_ciphertext,
            message_id=message_id,
            actor_type="reporter",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "mailbox_attachment_uploaded",
        case_number=session.case_number,
        message_id=str(message_id),
        filename=file.filename,
    )

    return AttachmentSummary.model_validate(attachment)


# ── POST /reports/mailbox/attachments ────────────────────────
# Direct attachment upload (without requiring a messageId).
# Used by the reporter frontend immediately after report creation.


@router.post(
    "/mailbox/attachments",
    response_model=AttachmentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attachment directly to the report",
    responses={
        400: {"description": "File validation failed"},
    },
)
async def upload_direct_attachment(
    file: UploadFile,
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AttachmentSummary:
    """Upload a file attachment directly to the report.

    Creates an initial system message (if none exists) and attaches
    the file to it.  This endpoint is designed for use immediately
    after report creation, before the reporter has sent any messages.
    """
    # Find or create an initial message for this report.
    msg_service = MessageService(db, session.tenant_id)
    initial_message = await msg_service.get_or_create_initial_message(
        report_id=session.report_id,
    )

    data = await file.read()

    dek_ciphertext = await _get_tenant_dek_ciphertext(db, session.tenant_id)

    file_service = FileService(
        db,
        session.tenant_id,
        settings.encryption_master_key,
    )

    try:
        await file_service.validate_upload(
            file_size=len(data),
            message_id=initial_message.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        attachment = await file_service.upload_file(
            report_id=session.report_id,
            filename=file.filename or "unnamed",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            tenant_dek_ciphertext=dek_ciphertext,
            message_id=initial_message.id,
            actor_type="reporter",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "direct_attachment_uploaded",
        case_number=session.case_number,
        filename=file.filename,
    )

    return AttachmentSummary.model_validate(attachment)


# ── GET /reports/mailbox/attachments/{attachment_id} ─────────


@router.get(
    "/mailbox/attachments/{attachment_id}",
    summary="Download a file attachment",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        404: {"description": "Attachment not found"},
    },
)
async def download_attachment(
    attachment_id: uuid.UUID,
    session: Annotated[MailboxSession, Depends(get_mailbox_session)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Download and decrypt a file attachment.

    The file is decrypted from AES-256-GCM and streamed to the client
    with the original filename and content type.  SHA-256 integrity
    is verified after decryption.
    """
    # Fetch tenant DEK ciphertext for envelope decryption.
    dek_ciphertext = await _get_tenant_dek_ciphertext(db, session.tenant_id)

    file_service = FileService(
        db,
        session.tenant_id,
        settings.encryption_master_key,
    )

    try:
        plaintext, attachment = await file_service.download_file(
            attachment_id,
            tenant_dek_ciphertext=dek_ciphertext,
            actor_type="reporter",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found.",
        )

    # Verify the attachment belongs to the reporter's report.
    if attachment.report_id != session.report_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found.",
        )

    logger.info(
        "mailbox_attachment_downloaded",
        case_number=session.case_number,
        attachment_id=str(attachment_id),
        filename=attachment.original_filename,
    )

    return StreamingResponse(
        io.BytesIO(plaintext),
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{attachment.original_filename}"'
            ),
            "Content-Length": str(len(plaintext)),
        },
    )
