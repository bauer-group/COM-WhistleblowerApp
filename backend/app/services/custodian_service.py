"""Hinweisgebersystem -- Custodian (Identity Disclosure) Business Service.

Implements the 4-eyes principle workflow for sealed reporter identity
disclosure, as required by §8 HinSchG (anonymity protection).

Workflow
--------
1. **Handler requests** disclosure → ``request_disclosure()``
   - Status: PENDING.
   - Handler must provide a mandatory reason.
2. **Custodian decides** → ``decide_disclosure()``
   - Custodian (a user with ``is_custodian=True``) approves or rejects.
   - If approved, status transitions to APPROVED.
   - If rejected, status transitions to REJECTED.
3. **Identity revealed** → ``reveal_identity()``
   - Only if status == APPROVED.
   - Returns the decrypted reporter identity fields.
   - Logged as a separate audit event (``IDENTITY_DISCLOSED``).

Every step is logged in the immutable ``audit_logs`` table, providing a
complete audit trail for compliance officers.  Disclosure requests can
also expire (via background task) if not acted upon within a
configurable period.

Usage::

    from app.services.custodian_service import CustodianService

    service = CustodianService(session, tenant_id)
    disclosure = await service.request_disclosure(
        report_id=report_id,
        requester_id=handler_id,
        reason="Investigation requires identity for witness interview.",
    )
    disclosure = await service.decide_disclosure(
        disclosure_id=disclosure.id,
        custodian_id=custodian_id,
        approved=True,
        decision_reason="Justified for legal proceedings.",
    )
    identity = await service.reveal_identity(
        disclosure_id=disclosure.id,
        actor_id=handler_id,
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.identity_disclosure import DisclosureStatus, IdentityDisclosure
from app.models.report import Report
from app.models.user import User
from app.repositories.audit_repo import AuditRepository

logger = structlog.get_logger(__name__)


class CustodianService:
    """Business logic for the 4-eyes identity disclosure workflow.

    The 4-eyes principle ensures that no single person can access
    sealed reporter identity data.  A handler initiates the request
    and a designated custodian (``User.is_custodian == True``) must
    independently approve it before the identity is revealed.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    tenant_id:
        UUID of the current tenant (from middleware).
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._audit_repo = AuditRepository(session)

    # ── Step 1: Handler requests disclosure ──────────────────────

    async def request_disclosure(
        self,
        *,
        report_id: uuid.UUID,
        requester_id: uuid.UUID,
        reason: str,
    ) -> IdentityDisclosure:
        """Create a new identity disclosure request.

        The requesting user must be a handler or admin with access to
        the report.  A mandatory reason must be provided for audit
        compliance.

        Parameters
        ----------
        report_id:
            UUID of the report whose identity is requested.
        requester_id:
            UUID of the handler requesting disclosure.
        reason:
            Mandatory justification for the disclosure request.

        Returns
        -------
        IdentityDisclosure
            The newly created disclosure request in PENDING status.

        Raises
        ------
        ValueError
            If the report does not exist, is not anonymous, or there
            is already a pending disclosure request for this report.
        """
        # Validate report exists and belongs to the tenant
        report = await self._get_report(report_id)
        if report is None:
            raise ValueError(
                f"Report {report_id!r} not found or does not belong "
                f"to the current tenant."
            )

        # Validate the report is anonymous (non-anonymous reports have
        # identity visible by default)
        if not report.is_anonymous:
            raise ValueError(
                "Identity disclosure is not required for non-anonymous "
                "reports.  Reporter identity is already available."
            )

        # Prevent duplicate pending requests for the same report
        existing = await self._get_pending_disclosure(report_id)
        if existing is not None:
            raise ValueError(
                f"A pending disclosure request already exists for "
                f"report {report_id!r} (disclosure ID: {existing.id})."
            )

        # Validate the requester is not a custodian (separation of duties)
        requester = await self._get_user(requester_id)
        if requester is not None and requester.is_custodian:
            raise ValueError(
                "A custodian cannot request identity disclosure.  "
                "Separation of duties requires a handler to initiate "
                "the request."
            )

        # Validate reason is not empty
        if not reason or not reason.strip():
            raise ValueError(
                "A reason must be provided for the identity disclosure "
                "request."
            )

        disclosure = IdentityDisclosure(
            report_id=report_id,
            tenant_id=self._tenant_id,
            requester_id=requester_id,
            reason=reason.strip(),
            status=DisclosureStatus.PENDING,
        )
        self._session.add(disclosure)
        await self._session.flush()
        await self._session.refresh(disclosure)

        # Audit trail
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.IDENTITY_DISCLOSURE_REQUESTED,
            resource_type="identity_disclosure",
            resource_id=str(disclosure.id),
            actor_id=requester_id,
            actor_type="user",
            details={
                "report_id": str(report_id),
                "reason": reason.strip(),
            },
        )

        logger.info(
            "identity_disclosure_requested",
            disclosure_id=str(disclosure.id),
            report_id=str(report_id),
            requester_id=str(requester_id),
        )

        return disclosure

    # ── Step 2: Custodian decides (approve / reject) ─────────────

    async def decide_disclosure(
        self,
        *,
        disclosure_id: uuid.UUID,
        custodian_id: uuid.UUID,
        approved: bool,
        decision_reason: str | None = None,
    ) -> IdentityDisclosure:
        """Approve or reject an identity disclosure request.

        Only users with ``is_custodian=True`` can make this decision.
        The custodian must be different from the requester (4-eyes
        principle).

        Parameters
        ----------
        disclosure_id:
            UUID of the disclosure request to decide.
        custodian_id:
            UUID of the custodian making the decision.
        approved:
            ``True`` to approve, ``False`` to reject.
        decision_reason:
            Optional reason for the decision (recommended for audit).

        Returns
        -------
        IdentityDisclosure
            The updated disclosure with the decision recorded.

        Raises
        ------
        ValueError
            If the disclosure is not found, not in PENDING status,
            the custodian is not authorised, or the custodian is the
            same as the requester.
        """
        # Fetch the disclosure
        disclosure = await self._get_disclosure(disclosure_id)
        if disclosure is None:
            raise ValueError(
                f"Disclosure request {disclosure_id!r} not found or "
                f"does not belong to the current tenant."
            )

        # Must be in PENDING status
        if disclosure.status != DisclosureStatus.PENDING:
            raise ValueError(
                f"Disclosure request {disclosure_id!r} is not pending "
                f"(current status: {disclosure.status.value}).  Only "
                f"pending requests can be decided."
            )

        # Validate the custodian is authorised
        custodian = await self._get_user(custodian_id)
        if custodian is None:
            raise ValueError(
                f"User {custodian_id!r} not found or does not belong "
                f"to the current tenant."
            )
        if not custodian.is_custodian:
            raise ValueError(
                f"User {custodian_id!r} is not designated as a "
                f"custodian and cannot approve or reject disclosure "
                f"requests."
            )
        if not custodian.is_active:
            raise ValueError(
                f"Custodian {custodian_id!r} is deactivated and "
                f"cannot make decisions."
            )

        # 4-eyes principle: custodian must differ from requester
        if custodian_id == disclosure.requester_id:
            raise ValueError(
                "The 4-eyes principle requires the custodian to be "
                "a different person than the requester.  The same user "
                "cannot both request and approve identity disclosure."
            )

        # Apply the decision
        new_status = (
            DisclosureStatus.APPROVED if approved
            else DisclosureStatus.REJECTED
        )
        disclosure.status = new_status
        disclosure.custodian_id = custodian_id
        disclosure.decided_at = datetime.now(timezone.utc)
        if decision_reason:
            disclosure.decision_reason = decision_reason.strip()

        await self._session.flush()
        await self._session.refresh(disclosure)

        # Audit trail
        audit_action = (
            AuditAction.IDENTITY_DISCLOSURE_APPROVED if approved
            else AuditAction.IDENTITY_DISCLOSURE_REJECTED
        )
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=audit_action,
            resource_type="identity_disclosure",
            resource_id=str(disclosure.id),
            actor_id=custodian_id,
            actor_type="user",
            details={
                "report_id": str(disclosure.report_id),
                "requester_id": str(disclosure.requester_id),
                "decision": "approved" if approved else "rejected",
                "decision_reason": decision_reason,
            },
        )

        logger.info(
            "identity_disclosure_decided",
            disclosure_id=str(disclosure.id),
            report_id=str(disclosure.report_id),
            custodian_id=str(custodian_id),
            decision="approved" if approved else "rejected",
        )

        return disclosure

    # ── Step 3: Identity revealed ────────────────────────────────

    async def reveal_identity(
        self,
        *,
        disclosure_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict[str, str | None]:
        """Reveal the sealed reporter identity after approved disclosure.

        Only callable when the disclosure status is APPROVED.  Returns
        the decrypted reporter identity fields and logs the access as
        a separate audit event.

        Parameters
        ----------
        disclosure_id:
            UUID of the approved disclosure request.
        actor_id:
            UUID of the user accessing the identity (must be the
            original requester).

        Returns
        -------
        dict[str, str | None]
            Dictionary with keys ``"reporter_name"``,
            ``"reporter_email"``, and ``"reporter_phone"``.

        Raises
        ------
        ValueError
            If the disclosure is not found, not approved, or the
            actor is not the original requester.
        """
        disclosure = await self._get_disclosure(disclosure_id)
        if disclosure is None:
            raise ValueError(
                f"Disclosure request {disclosure_id!r} not found or "
                f"does not belong to the current tenant."
            )

        if disclosure.status != DisclosureStatus.APPROVED:
            raise ValueError(
                f"Disclosure request {disclosure_id!r} is not approved "
                f"(current status: {disclosure.status.value}).  Identity "
                f"can only be revealed after custodian approval."
            )

        # Only the original requester may view the identity
        if actor_id != disclosure.requester_id:
            raise ValueError(
                "Only the handler who originally requested the "
                "disclosure may view the revealed identity."
            )

        # Fetch the report to read the identity fields
        report = await self._get_report(disclosure.report_id)
        if report is None:
            raise ValueError(
                f"Report {disclosure.report_id!r} not found."
            )

        # Read the PGPString-decrypted fields (transparently decrypted
        # by the ORM when the session has the correct RLS context)
        identity = {
            "reporter_name": report.reporter_name_encrypted,
            "reporter_email": report.reporter_email_encrypted,
            "reporter_phone": report.reporter_phone_encrypted,
        }

        # Audit the identity access as a separate event
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.IDENTITY_DISCLOSED,
            resource_type="identity_disclosure",
            resource_id=str(disclosure.id),
            actor_id=actor_id,
            actor_type="user",
            details={
                "report_id": str(disclosure.report_id),
                "disclosure_id": str(disclosure.id),
                "custodian_id": str(disclosure.custodian_id),
            },
        )

        logger.info(
            "identity_disclosed",
            disclosure_id=str(disclosure.id),
            report_id=str(disclosure.report_id),
            actor_id=str(actor_id),
        )

        return identity

    # ── Expiration ───────────────────────────────────────────────

    async def expire_pending_disclosures(
        self,
        *,
        older_than: datetime,
    ) -> int:
        """Expire pending disclosure requests older than a given date.

        Used by a background task to automatically expire stale
        requests that were never decided by a custodian.

        Parameters
        ----------
        older_than:
            Requests created before this timestamp are expired.

        Returns
        -------
        int
            Number of disclosure requests that were expired.
        """
        stmt = (
            select(IdentityDisclosure)
            .where(
                IdentityDisclosure.tenant_id == self._tenant_id,
                IdentityDisclosure.status == DisclosureStatus.PENDING,
                IdentityDisclosure.created_at < older_than,
            )
        )
        result = await self._session.execute(stmt)
        disclosures = list(result.scalars().all())

        expired_count = 0
        for disclosure in disclosures:
            disclosure.status = DisclosureStatus.EXPIRED
            disclosure.decided_at = datetime.now(timezone.utc)
            expired_count += 1

            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.IDENTITY_DISCLOSURE_REJECTED,
                resource_type="identity_disclosure",
                resource_id=str(disclosure.id),
                actor_type="system",
                details={
                    "report_id": str(disclosure.report_id),
                    "reason": "expired",
                    "expired_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        if expired_count > 0:
            await self._session.flush()
            logger.info(
                "identity_disclosures_expired",
                count=expired_count,
                older_than=older_than.isoformat(),
            )

        return expired_count

    # ── Listing ──────────────────────────────────────────────────

    async def list_disclosures_for_report(
        self,
        report_id: uuid.UUID,
    ) -> list[IdentityDisclosure]:
        """List all disclosure requests for a report.

        Returns requests ordered by creation time (newest first).

        Parameters
        ----------
        report_id:
            UUID of the report.

        Returns
        -------
        list[IdentityDisclosure]
            All disclosure requests for the report.
        """
        stmt = (
            select(IdentityDisclosure)
            .where(
                IdentityDisclosure.report_id == report_id,
                IdentityDisclosure.tenant_id == self._tenant_id,
            )
            .order_by(IdentityDisclosure.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_disclosure_by_id(
        self,
        disclosure_id: uuid.UUID,
    ) -> IdentityDisclosure | None:
        """Fetch a single disclosure request by ID.

        Returns ``None`` if not found or not in the current tenant.
        """
        return await self._get_disclosure(disclosure_id)

    async def list_pending_disclosures(self) -> list[IdentityDisclosure]:
        """List all pending disclosure requests for the tenant.

        Used by the custodian dashboard to display actionable requests.

        Returns
        -------
        list[IdentityDisclosure]
            All pending disclosure requests, newest first.
        """
        stmt = (
            select(IdentityDisclosure)
            .where(
                IdentityDisclosure.tenant_id == self._tenant_id,
                IdentityDisclosure.status == DisclosureStatus.PENDING,
            )
            .order_by(IdentityDisclosure.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Private helpers ──────────────────────────────────────────

    async def _get_report(self, report_id: uuid.UUID) -> Report | None:
        """Fetch a report within the current tenant context."""
        stmt = select(Report).where(
            Report.id == report_id,
            Report.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_user(self, user_id: uuid.UUID) -> User | None:
        """Fetch a user within the current tenant context."""
        stmt = select(User).where(
            User.id == user_id,
            User.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_disclosure(
        self,
        disclosure_id: uuid.UUID,
    ) -> IdentityDisclosure | None:
        """Fetch a disclosure request within the current tenant context."""
        stmt = select(IdentityDisclosure).where(
            IdentityDisclosure.id == disclosure_id,
            IdentityDisclosure.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_pending_disclosure(
        self,
        report_id: uuid.UUID,
    ) -> IdentityDisclosure | None:
        """Fetch the pending disclosure request for a report, if any."""
        stmt = select(IdentityDisclosure).where(
            IdentityDisclosure.report_id == report_id,
            IdentityDisclosure.tenant_id == self._tenant_id,
            IdentityDisclosure.status == DisclosureStatus.PENDING,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
