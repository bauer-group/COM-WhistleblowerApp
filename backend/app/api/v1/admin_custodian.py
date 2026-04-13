"""Hinweisgebersystem – Admin Custodian (Identity Disclosure) API Endpoints.

Implements the 4-eyes principle workflow API for sealed reporter identity
disclosure, as required by §8 HinSchG (anonymity protection).

Provides:
- **POST /admin/custodian/disclosures** — Request identity disclosure
  for an anonymous report (handler action).
- **POST /admin/custodian/disclosures/{disclosure_id}/decide** — Approve
  or reject a pending disclosure request (custodian action).
- **GET /admin/custodian/disclosures/pending** — List all pending
  disclosure requests for the tenant (custodian dashboard).
- **GET /admin/custodian/disclosures/{disclosure_id}** — Get a single
  disclosure request by ID.
- **GET /admin/custodian/reports/{report_id}/disclosures** — List all
  disclosure requests for a specific report.
- **POST /admin/custodian/disclosures/{disclosure_id}/reveal** — Reveal
  the sealed reporter identity after approved disclosure.

All endpoints require OIDC-authenticated admin users with appropriate
custodian scopes.  Tenant isolation is enforced via Row-Level Security.

Usage::

    from app.api.v1.admin_custodian import router as admin_custodian_router
    api_v1_router.include_router(admin_custodian_router)
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.identity_disclosure import DisclosureStatus
from app.services.custodian_service import CustodianService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/custodian", tags=["admin-custodian"])


# ── Request / Response Schemas ───────────────────────────────


class DisclosureRequestCreate(BaseModel):
    """Schema for requesting identity disclosure."""

    model_config = ConfigDict(str_strip_whitespace=True)

    report_id: uuid.UUID = Field(
        description="UUID of the report whose identity is requested.",
    )
    reason: str = Field(
        min_length=10,
        max_length=2000,
        description=(
            "Mandatory justification for the disclosure request.  "
            "Must be at least 10 characters for audit compliance."
        ),
    )


class DisclosureDecisionRequest(BaseModel):
    """Schema for approving or rejecting a disclosure request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approved: bool = Field(
        description="``True`` to approve, ``False`` to reject.",
    )
    decision_reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional reason for the decision (recommended for audit).",
    )


class DisclosureResponse(BaseModel):
    """Response schema for an identity disclosure request."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    tenant_id: uuid.UUID
    requester_id: uuid.UUID
    reason: str
    status: DisclosureStatus
    custodian_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class IdentityRevealResponse(BaseModel):
    """Response containing the revealed reporter identity."""

    model_config = ConfigDict(frozen=True)

    reporter_name: str | None = Field(
        default=None,
        description="Decrypted reporter name.",
    )
    reporter_email: str | None = Field(
        default=None,
        description="Decrypted reporter email.",
    )
    reporter_phone: str | None = Field(
        default=None,
        description="Decrypted reporter phone number.",
    )
    disclosure_id: uuid.UUID = Field(
        description="UUID of the approved disclosure request.",
    )


# ── POST /admin/custodian/disclosures ────────────────────────


@router.post(
    "/disclosures",
    response_model=DisclosureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request identity disclosure for an anonymous report",
    responses={
        400: {"description": "Validation error (non-anonymous report, duplicate, etc.)"},
        403: {"description": "Insufficient permissions"},
    },
)
async def request_disclosure(
    body: DisclosureRequestCreate,
    user=Security(get_current_user, scopes=["custodian:request"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> DisclosureResponse:
    """Request identity disclosure for an anonymous report.

    The requesting user must be a handler or admin (not a custodian).
    A mandatory reason must be provided for audit compliance.  Only
    one pending disclosure request per report is allowed.

    The request enters PENDING status and must be approved by a
    designated custodian via the ``/decide`` endpoint.

    Requires ``custodian:request`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)

    try:
        disclosure = await service.request_disclosure(
            report_id=body.report_id,
            requester_id=user.id,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "admin_disclosure_requested",
        disclosure_id=str(disclosure.id),
        report_id=str(body.report_id),
        requester_email=user.email,
    )

    return DisclosureResponse.model_validate(disclosure)


# ── POST /admin/custodian/disclosures/{disclosure_id}/decide ──


@router.post(
    "/disclosures/{disclosure_id}/decide",
    response_model=DisclosureResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve or reject a disclosure request",
    responses={
        400: {"description": "Validation error (not pending, same user, etc.)"},
        403: {"description": "User is not a custodian"},
        404: {"description": "Disclosure request not found"},
    },
)
async def decide_disclosure(
    disclosure_id: uuid.UUID,
    body: DisclosureDecisionRequest,
    user=Security(get_current_user, scopes=["custodian:approve"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> DisclosureResponse:
    """Approve or reject a pending identity disclosure request.

    Only users designated as custodians (``is_custodian=True``) may
    decide on disclosure requests.  The custodian must be a different
    person than the requester (4-eyes principle).

    If approved, the identity can be revealed via the ``/reveal``
    endpoint.  If rejected, the disclosure request is permanently
    closed.

    Requires ``custodian:approve`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)

    try:
        disclosure = await service.decide_disclosure(
            disclosure_id=disclosure_id,
            custodian_id=user.id,
            approved=body.approved,
            decision_reason=body.decision_reason,
        )
    except ValueError as exc:
        error_msg = str(exc)
        # Differentiate between "not found" and other validation errors
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        if "not designated as a custodian" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    decision = "approved" if body.approved else "rejected"
    logger.info(
        "admin_disclosure_decided",
        disclosure_id=str(disclosure_id),
        custodian_email=user.email,
        decision=decision,
    )

    return DisclosureResponse.model_validate(disclosure)


# ── GET /admin/custodian/disclosures/pending ─────────────────


@router.get(
    "/disclosures/pending",
    response_model=list[DisclosureResponse],
    status_code=status.HTTP_200_OK,
    summary="List pending disclosure requests",
)
async def list_pending_disclosures(
    user=Security(get_current_user, scopes=["custodian:approve"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[DisclosureResponse]:
    """List all pending identity disclosure requests for the tenant.

    Used by custodians to see which requests are awaiting their
    decision.  Returns requests ordered by creation time (newest first).

    Requires ``custodian:approve`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)
    disclosures = await service.list_pending_disclosures()

    logger.info(
        "admin_pending_disclosures_listed",
        custodian_email=user.email,
        count=len(disclosures),
    )

    return [
        DisclosureResponse.model_validate(d) for d in disclosures
    ]


# ── GET /admin/custodian/disclosures/{disclosure_id} ─────────


@router.get(
    "/disclosures/{disclosure_id}",
    response_model=DisclosureResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a disclosure request by ID",
    responses={
        404: {"description": "Disclosure request not found"},
    },
)
async def get_disclosure(
    disclosure_id: uuid.UUID,
    user=Security(get_current_user, scopes=["custodian:request"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> DisclosureResponse:
    """Get a single identity disclosure request by ID.

    Requires ``custodian:request`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)
    disclosure = await service.get_disclosure_by_id(disclosure_id)

    if disclosure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disclosure request not found.",
        )

    return DisclosureResponse.model_validate(disclosure)


# ── GET /admin/custodian/reports/{report_id}/disclosures ─────


@router.get(
    "/reports/{report_id}/disclosures",
    response_model=list[DisclosureResponse],
    status_code=status.HTTP_200_OK,
    summary="List disclosure requests for a report",
)
async def list_report_disclosures(
    report_id: uuid.UUID,
    user=Security(get_current_user, scopes=["custodian:request"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[DisclosureResponse]:
    """List all identity disclosure requests for a specific report.

    Returns all requests (pending, approved, rejected, expired) ordered
    by creation time (newest first).  Useful for viewing the disclosure
    history on the case detail page.

    Requires ``custodian:request`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)
    disclosures = await service.list_disclosures_for_report(report_id)

    return [
        DisclosureResponse.model_validate(d) for d in disclosures
    ]


# ── POST /admin/custodian/disclosures/{disclosure_id}/reveal ──


@router.post(
    "/disclosures/{disclosure_id}/reveal",
    response_model=IdentityRevealResponse,
    status_code=status.HTTP_200_OK,
    summary="Reveal sealed reporter identity after approved disclosure",
    responses={
        400: {"description": "Disclosure not approved or actor mismatch"},
        404: {"description": "Disclosure request not found"},
    },
)
async def reveal_identity(
    disclosure_id: uuid.UUID,
    user=Security(get_current_user, scopes=["custodian:request"]),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
) -> IdentityRevealResponse:
    """Reveal the sealed reporter identity after approved disclosure.

    Only callable when the disclosure status is APPROVED.  Only the
    original handler who requested the disclosure may view the identity.
    The access is logged as a separate audit event for compliance.

    Returns the decrypted reporter identity fields (name, email, phone).

    Requires ``custodian:request`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    service = CustodianService(db, tenant_id)

    try:
        identity = await service.reveal_identity(
            disclosure_id=disclosure_id,
            actor_id=user.id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    logger.info(
        "admin_identity_revealed",
        disclosure_id=str(disclosure_id),
        actor_email=user.email,
    )

    return IdentityRevealResponse(
        reporter_name=identity.get("reporter_name"),
        reporter_email=identity.get("reporter_email"),
        reporter_phone=identity.get("reporter_phone"),
        disclosure_id=disclosure_id,
    )
