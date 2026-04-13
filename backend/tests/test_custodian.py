"""Hinweisgebersystem -- Custodian (4-Eyes Identity Disclosure) Tests.

Tests:
- Full 4-eyes disclosure workflow: request → custodian approve → identity
  disclosed to the original requester.
- Single approval insufficient (rejection path).
- Separation of duties (requester ≠ custodian).
- Duplicate pending request prevention.
- Non-anonymous report rejection.
- Audit trail for every workflow step.
- Expiration of stale pending requests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_disclosure import DisclosureStatus, IdentityDisclosure
from app.models.report import Channel, Priority, Report, ReportStatus
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.custodian_service import CustodianService

pytestmark = pytest.mark.asyncio

# ── Test Constants ───────────────────────────────────────────

_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_HANDLER_ID = uuid.UUID("00000000-0000-4000-8000-000000000030")
_CUSTODIAN_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture()
async def tenant(db_session: AsyncSession) -> Tenant:
    """Create and persist a test tenant."""
    tenant = Tenant(
        id=_TENANT_ID,
        slug="custodian-test",
        name="Custodian Test Org",
        is_active=True,
        config={},
        dek_ciphertext="c" * 64,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture()
async def handler(db_session: AsyncSession, tenant: Tenant) -> User:
    """Create a handler user (non-custodian) who can request disclosure."""
    user = User(
        id=_HANDLER_ID,
        tenant_id=_TENANT_ID,
        email="handler@test.example.com",
        display_name="Test Handler",
        oidc_subject="oidc-sub-handler",
        role=UserRole.HANDLER,
        is_active=True,
        is_custodian=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture()
async def custodian(db_session: AsyncSession, tenant: Tenant) -> User:
    """Create a custodian user who can approve/reject disclosures."""
    user = User(
        id=_CUSTODIAN_ID,
        tenant_id=_TENANT_ID,
        email="custodian@test.example.com",
        display_name="Test Custodian",
        oidc_subject="oidc-sub-custodian",
        role=UserRole.TENANT_ADMIN,
        is_active=True,
        is_custodian=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture()
async def anonymous_report(
    db_session: AsyncSession, tenant: Tenant
) -> Report:
    """Create an anonymous report with sealed identity fields."""
    now = datetime.now(timezone.utc)
    report = Report(
        id=uuid.uuid4(),
        tenant_id=_TENANT_ID,
        case_number="HWS-CUSTODIANTEST",
        passphrase_hash="$2b$12$fakehash",
        is_anonymous=True,
        channel=Channel.HINSCHG,
        status=ReportStatus.IN_BEARBEITUNG,
        priority=Priority.MEDIUM,
        language="de",
        version=1,
        created_at=now,
        updated_at=now,
        confirmation_deadline=now + timedelta(days=7),
        feedback_deadline=now + timedelta(days=90),
        # Encrypted identity fields (simulated plaintext for SQLite tests)
        reporter_name_encrypted=b"Jane Doe",
        reporter_email_encrypted=b"jane@example.com",
        reporter_phone_encrypted=b"+491234567890",
    )
    db_session.add(report)
    await db_session.flush()
    return report


@pytest.fixture()
async def non_anonymous_report(
    db_session: AsyncSession, tenant: Tenant
) -> Report:
    """Create a non-anonymous report (identity already visible)."""
    now = datetime.now(timezone.utc)
    report = Report(
        id=uuid.uuid4(),
        tenant_id=_TENANT_ID,
        case_number="HWS-NONANONYMOUS0",
        passphrase_hash="$2b$12$fakehash",
        is_anonymous=False,
        channel=Channel.HINSCHG,
        status=ReportStatus.IN_BEARBEITUNG,
        priority=Priority.MEDIUM,
        language="de",
        version=1,
        created_at=now,
        updated_at=now,
        confirmation_deadline=now + timedelta(days=7),
        feedback_deadline=now + timedelta(days=90),
    )
    db_session.add(report)
    await db_session.flush()
    return report


@pytest.fixture()
def custodian_service(db_session: AsyncSession) -> CustodianService:
    """Create a CustodianService bound to the test session."""
    return CustodianService(db_session, _TENANT_ID)


# ── Full 4-Eyes Workflow ────────────────────────────────────


class TestFourEyesWorkflow:
    """Tests for the complete 4-eyes identity disclosure workflow."""

    async def test_full_workflow_request_approve_reveal(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Full workflow: request → approve → reveal identity."""
        # Step 1: Handler requests disclosure
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Need identity for witness interview.",
        )

        assert disclosure.status == DisclosureStatus.PENDING
        assert disclosure.requester_id == handler.id
        assert disclosure.reason == "Need identity for witness interview."

        # Step 2: Custodian approves
        approved = await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=True,
            decision_reason="Justified for legal proceedings.",
        )

        assert approved.status == DisclosureStatus.APPROVED
        assert approved.custodian_id == custodian.id
        assert approved.decided_at is not None
        assert approved.decision_reason == "Justified for legal proceedings."

        # Step 3: Handler reveals identity
        identity = await custodian_service.reveal_identity(
            disclosure_id=disclosure.id,
            actor_id=handler.id,
        )

        assert "reporter_name" in identity
        assert "reporter_email" in identity
        assert "reporter_phone" in identity

    async def test_workflow_request_reject(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Workflow: request → reject.  Identity must remain sealed."""
        # Step 1: Handler requests
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation purposes.",
        )

        # Step 2: Custodian rejects
        rejected = await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=False,
            decision_reason="Insufficient justification.",
        )

        assert rejected.status == DisclosureStatus.REJECTED
        assert rejected.custodian_id == custodian.id
        assert rejected.decision_reason == "Insufficient justification."

        # Step 3: Attempting to reveal must fail
        with pytest.raises(ValueError, match="not approved"):
            await custodian_service.reveal_identity(
                disclosure_id=disclosure.id,
                actor_id=handler.id,
            )


# ── Single Approval Insufficient ────────────────────────────


class TestSingleApprovalInsufficient:
    """Tests that a single person cannot complete the entire workflow."""

    async def test_custodian_cannot_request_disclosure(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        custodian: User,
    ):
        """A custodian cannot request disclosure (separation of duties)."""
        with pytest.raises(ValueError, match="custodian cannot request"):
            await custodian_service.request_disclosure(
                report_id=anonymous_report.id,
                requester_id=custodian.id,
                reason="I want to see the identity.",
            )

    async def test_requester_cannot_approve_own_request(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        custodian: User,
    ):
        """A custodian who requested cannot also approve (4-eyes principle).

        Since the service prevents custodians from *requesting* disclosure
        (separation of duties), we create the disclosure record directly
        in the database to test the defence-in-depth 4-eyes check on the
        approval path.
        """
        disclosure = IdentityDisclosure(
            id=uuid.uuid4(),
            tenant_id=anonymous_report.tenant_id,
            report_id=anonymous_report.id,
            requester_id=custodian.id,
            reason="Need identity for investigation.",
            status=DisclosureStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        db_session.add(disclosure)
        await db_session.flush()

        with pytest.raises(ValueError, match="4-eyes principle"):
            await custodian_service.decide_disclosure(
                disclosure_id=disclosure.id,
                custodian_id=custodian.id,
                approved=True,
            )

    async def test_non_custodian_cannot_approve(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """A user who is not a custodian cannot approve disclosure."""
        # Create a second non-custodian user
        other_handler_id = uuid.uuid4()
        other_handler = User(
            id=other_handler_id,
            tenant_id=_TENANT_ID,
            email="other-handler@test.example.com",
            display_name="Other Handler",
            oidc_subject="oidc-sub-other-handler",
            role=UserRole.HANDLER,
            is_active=True,
            is_custodian=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(other_handler)
        await db_session.flush()

        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation requires identity.",
        )

        with pytest.raises(ValueError, match="not designated as a custodian"):
            await custodian_service.decide_disclosure(
                disclosure_id=disclosure.id,
                custodian_id=other_handler_id,
                approved=True,
            )

    async def test_only_requester_can_reveal(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Only the original requester may view the revealed identity."""
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=True,
        )

        # Custodian (different person) tries to reveal
        with pytest.raises(ValueError, match="originally requested"):
            await custodian_service.reveal_identity(
                disclosure_id=disclosure.id,
                actor_id=custodian.id,
            )


# ── Validation Guards ───────────────────────────────────────


class TestDisclosureValidation:
    """Tests for validation guards in the disclosure workflow."""

    async def test_non_anonymous_report_rejected(
        self,
        custodian_service: CustodianService,
        non_anonymous_report: Report,
        handler: User,
    ):
        """Disclosure request for non-anonymous reports must be rejected."""
        with pytest.raises(ValueError, match="not required for non-anonymous"):
            await custodian_service.request_disclosure(
                report_id=non_anonymous_report.id,
                requester_id=handler.id,
                reason="Want to see identity.",
            )

    async def test_duplicate_pending_request_rejected(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
    ):
        """A second pending request for the same report must be rejected."""
        await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="First request.",
        )

        with pytest.raises(ValueError, match="pending disclosure request already exists"):
            await custodian_service.request_disclosure(
                report_id=anonymous_report.id,
                requester_id=handler.id,
                reason="Duplicate request.",
            )

    async def test_empty_reason_rejected(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
    ):
        """Disclosure request with empty reason must be rejected."""
        with pytest.raises(ValueError, match="reason must be provided"):
            await custodian_service.request_disclosure(
                report_id=anonymous_report.id,
                requester_id=handler.id,
                reason="   ",
            )

    async def test_nonexistent_report_rejected(
        self,
        custodian_service: CustodianService,
        handler: User,
        tenant: Tenant,
    ):
        """Disclosure request for non-existent report must be rejected."""
        fake_report_id = uuid.uuid4()
        with pytest.raises(ValueError, match="not found"):
            await custodian_service.request_disclosure(
                report_id=fake_report_id,
                requester_id=handler.id,
                reason="Report does not exist.",
            )

    async def test_deactivated_custodian_cannot_decide(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """A deactivated custodian must not be able to decide."""
        inactive_custodian_id = uuid.uuid4()
        inactive_custodian = User(
            id=inactive_custodian_id,
            tenant_id=_TENANT_ID,
            email="inactive-custodian@test.example.com",
            display_name="Inactive Custodian",
            oidc_subject="oidc-sub-inactive-custodian",
            role=UserRole.TENANT_ADMIN,
            is_active=False,
            is_custodian=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(inactive_custodian)
        await db_session.flush()

        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )

        with pytest.raises(ValueError, match="deactivated"):
            await custodian_service.decide_disclosure(
                disclosure_id=disclosure.id,
                custodian_id=inactive_custodian_id,
                approved=True,
            )

    async def test_already_decided_cannot_decide_again(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """An already decided disclosure cannot be decided again."""
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=True,
        )

        with pytest.raises(ValueError, match="not pending"):
            await custodian_service.decide_disclosure(
                disclosure_id=disclosure.id,
                custodian_id=custodian.id,
                approved=False,
            )


# ── Audit Trail ─────────────────────────────────────────────


class TestDisclosureAuditTrail:
    """Tests that the disclosure workflow produces audit log entries."""

    async def test_request_creates_audit_entry(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """Requesting disclosure must create an audit log entry."""
        from app.models.audit_log import AuditAction, AuditLog

        await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation needs identity.",
        )

        stmt = select(AuditLog).where(
            AuditLog.action == AuditAction.IDENTITY_DISCLOSURE_REQUESTED,
        )
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1
        assert entries[0].actor_id == handler.id

    async def test_approval_creates_audit_entry(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Approving disclosure must create an audit log entry."""
        from app.models.audit_log import AuditAction, AuditLog

        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=True,
        )

        stmt = select(AuditLog).where(
            AuditLog.action == AuditAction.IDENTITY_DISCLOSURE_APPROVED,
        )
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1
        assert entries[0].actor_id == custodian.id

    async def test_rejection_creates_audit_entry(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Rejecting disclosure must create an audit log entry."""
        from app.models.audit_log import AuditAction, AuditLog

        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=False,
        )

        stmt = select(AuditLog).where(
            AuditLog.action == AuditAction.IDENTITY_DISCLOSURE_REJECTED,
        )
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1

    async def test_reveal_creates_audit_entry(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """Revealing identity must create a separate IDENTITY_DISCLOSED entry."""
        from app.models.audit_log import AuditAction, AuditLog

        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=True,
        )
        await custodian_service.reveal_identity(
            disclosure_id=disclosure.id,
            actor_id=handler.id,
        )

        stmt = select(AuditLog).where(
            AuditLog.action == AuditAction.IDENTITY_DISCLOSED,
        )
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1
        assert entries[0].actor_id == handler.id


# ── Expiration ──────────────────────────────────────────────


class TestDisclosureExpiration:
    """Tests for automatic expiration of stale pending disclosures."""

    async def test_expire_stale_requests(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """Pending requests older than the cutoff must be expired."""
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )

        # Manually backdate the disclosure to simulate staleness
        disclosure.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        await db_session.flush()

        # Expire anything older than 7 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        count = await custodian_service.expire_pending_disclosures(
            older_than=cutoff,
        )

        assert count == 1

        # Verify the disclosure is now expired
        stmt = select(IdentityDisclosure).where(
            IdentityDisclosure.id == disclosure.id,
        )
        result = await db_session.execute(stmt)
        updated = result.scalar_one()
        assert updated.status == DisclosureStatus.EXPIRED

    async def test_recent_requests_not_expired(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """Recent pending requests must not be expired."""
        await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Investigation.",
        )

        # Cutoff is in the past — the just-created request is newer
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        count = await custodian_service.expire_pending_disclosures(
            older_than=cutoff,
        )

        assert count == 0


# ── Listing ─────────────────────────────────────────────────


class TestDisclosureListing:
    """Tests for listing disclosure requests."""

    async def test_list_disclosures_for_report(
        self,
        db_session: AsyncSession,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        custodian: User,
    ):
        """list_disclosures_for_report must return all disclosures."""
        disclosure = await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="First request.",
        )
        # Reject first, then create a second
        await custodian_service.decide_disclosure(
            disclosure_id=disclosure.id,
            custodian_id=custodian.id,
            approved=False,
        )

        # Now a new request can be made since old one is rejected (not pending)
        await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Second request with more justification.",
        )

        disclosures = await custodian_service.list_disclosures_for_report(
            anonymous_report.id,
        )

        assert len(disclosures) == 2

    async def test_list_pending_disclosures(
        self,
        custodian_service: CustodianService,
        anonymous_report: Report,
        handler: User,
        tenant: Tenant,
    ):
        """list_pending_disclosures must return only PENDING requests."""
        await custodian_service.request_disclosure(
            report_id=anonymous_report.id,
            requester_id=handler.id,
            reason="Pending request.",
        )

        pending = await custodian_service.list_pending_disclosures()

        assert len(pending) == 1
        assert pending[0].status == DisclosureStatus.PENDING
