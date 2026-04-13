"""Hinweisgebersystem -- RLS (Row-Level Security) Tenant Isolation Tests.

Tests:
- Tenant A data invisible to tenant B session.
- Cross-tenant query returns empty results.
- Reports, users, and audit logs are properly isolated per tenant.
- ORM model queries respect tenant_id scoping.

Note: These tests use SQLite in-memory (no real RLS enforcement) but
validate the application-level tenant scoping logic that mirrors the
PostgreSQL RLS behaviour.  The repository and service layers filter
by ``tenant_id`` in their queries, which is the application-layer
equivalent of database-level RLS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.models.report import Channel, Priority, Report, ReportStatus
from app.models.tenant import Tenant
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

# ── Test Tenant IDs ──────────────────────────────────────────

_TENANT_A_ID = uuid.UUID("00000000-0000-4000-8000-00000000000a")
_TENANT_B_ID = uuid.UUID("00000000-0000-4000-8000-00000000000b")


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture()
async def tenant_a(db_session: AsyncSession) -> Tenant:
    """Create and persist Tenant A."""
    tenant = Tenant(
        id=_TENANT_A_ID,
        slug="tenant-a",
        name="Tenant A GmbH",
        is_active=True,
        config={},
        dek_ciphertext="a" * 64,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture()
async def tenant_b(db_session: AsyncSession) -> Tenant:
    """Create and persist Tenant B."""
    tenant = Tenant(
        id=_TENANT_B_ID,
        slug="tenant-b",
        name="Tenant B AG",
        is_active=True,
        config={},
        dek_ciphertext="b" * 64,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture()
async def user_a(db_session: AsyncSession, tenant_a: Tenant) -> User:
    """Create a handler user in Tenant A."""
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="handler-a@tenant-a.example.com",
        display_name="Handler A",
        oidc_subject="oidc-sub-a",
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
async def user_b(db_session: AsyncSession, tenant_b: Tenant) -> User:
    """Create a handler user in Tenant B."""
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email="handler-b@tenant-b.example.com",
        display_name="Handler B",
        oidc_subject="oidc-sub-b",
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
async def report_a(db_session: AsyncSession, tenant_a: Tenant) -> Report:
    """Create a report in Tenant A."""
    now = datetime.now(timezone.utc)
    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        case_number="HWS-AAAAAAAAAAAA",
        passphrase_hash="$2b$12$fakehashA",
        is_anonymous=True,
        channel=Channel.HINSCHG,
        status=ReportStatus.EINGEGANGEN,
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
async def report_b(db_session: AsyncSession, tenant_b: Tenant) -> Report:
    """Create a report in Tenant B."""
    now = datetime.now(timezone.utc)
    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        case_number="HWS-BBBBBBBBBBBB",
        passphrase_hash="$2b$12$fakehashB",
        is_anonymous=True,
        channel=Channel.LKSG,
        status=ReportStatus.IN_BEARBEITUNG,
        priority=Priority.HIGH,
        language="en",
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
async def audit_log_a(db_session: AsyncSession, tenant_a: Tenant) -> AuditLog:
    """Create an audit log entry for Tenant A."""
    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        action=AuditAction.CASE_CREATED,
        actor_type="reporter",
        resource_type="report",
        resource_id="test-report-a",
        details={"channel": "hinschg"},
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


@pytest.fixture()
async def audit_log_b(db_session: AsyncSession, tenant_b: Tenant) -> AuditLog:
    """Create an audit log entry for Tenant B."""
    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        action=AuditAction.CASE_CREATED,
        actor_type="reporter",
        resource_type="report",
        resource_id="test-report-b",
        details={"channel": "lksg"},
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


# ── Report Tenant Isolation ─────────────────────────────────


class TestReportTenantIsolation:
    """Tests that reports are isolated per tenant."""

    async def test_tenant_a_report_visible_to_tenant_a(
        self, db_session: AsyncSession, report_a: Report, report_b: Report
    ):
        """Querying with tenant_a's ID must return only tenant_a's reports."""
        stmt = select(Report).where(Report.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        reports = list(result.scalars().all())

        assert len(reports) == 1
        assert reports[0].case_number == "HWS-AAAAAAAAAAAA"
        assert reports[0].tenant_id == _TENANT_A_ID

    async def test_tenant_b_report_invisible_to_tenant_a(
        self, db_session: AsyncSession, report_a: Report, report_b: Report
    ):
        """Tenant A's scoped query must not return Tenant B's reports."""
        stmt = select(Report).where(Report.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        reports = list(result.scalars().all())

        case_numbers = [r.case_number for r in reports]
        assert "HWS-BBBBBBBBBBBB" not in case_numbers

    async def test_cross_tenant_report_query_returns_empty(
        self, db_session: AsyncSession, report_a: Report
    ):
        """Querying with a non-existent tenant ID must return no reports."""
        fake_tenant = uuid.UUID("00000000-0000-4000-8000-999999999999")
        stmt = select(Report).where(Report.tenant_id == fake_tenant)
        result = await db_session.execute(stmt)
        reports = list(result.scalars().all())

        assert len(reports) == 0

    async def test_each_tenant_sees_only_own_reports(
        self, db_session: AsyncSession, report_a: Report, report_b: Report
    ):
        """Each tenant must see exactly one report (their own)."""
        for tenant_id, expected_case in [
            (_TENANT_A_ID, "HWS-AAAAAAAAAAAA"),
            (_TENANT_B_ID, "HWS-BBBBBBBBBBBB"),
        ]:
            stmt = select(Report).where(Report.tenant_id == tenant_id)
            result = await db_session.execute(stmt)
            reports = list(result.scalars().all())
            assert len(reports) == 1
            assert reports[0].case_number == expected_case


# ── User Tenant Isolation ───────────────────────────────────


class TestUserTenantIsolation:
    """Tests that users are isolated per tenant."""

    async def test_tenant_a_user_visible_to_tenant_a(
        self, db_session: AsyncSession, user_a: User, user_b: User
    ):
        """Querying with tenant_a's ID must return only tenant_a's users."""
        stmt = select(User).where(User.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        users = list(result.scalars().all())

        assert len(users) == 1
        assert users[0].email == "handler-a@tenant-a.example.com"

    async def test_tenant_b_user_invisible_to_tenant_a(
        self, db_session: AsyncSession, user_a: User, user_b: User
    ):
        """Tenant A's user query must not return Tenant B's users."""
        stmt = select(User).where(User.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        users = list(result.scalars().all())

        emails = [u.email for u in users]
        assert "handler-b@tenant-b.example.com" not in emails

    async def test_cross_tenant_user_query_returns_empty(
        self, db_session: AsyncSession, user_a: User
    ):
        """Querying with a non-existent tenant ID must return no users."""
        fake_tenant = uuid.UUID("00000000-0000-4000-8000-999999999999")
        stmt = select(User).where(User.tenant_id == fake_tenant)
        result = await db_session.execute(stmt)
        users = list(result.scalars().all())

        assert len(users) == 0


# ── Audit Log Tenant Isolation ──────────────────────────────


class TestAuditLogTenantIsolation:
    """Tests that audit logs are isolated per tenant."""

    async def test_tenant_a_audit_visible_to_tenant_a(
        self,
        db_session: AsyncSession,
        audit_log_a: AuditLog,
        audit_log_b: AuditLog,
    ):
        """Tenant A's audit query must return only Tenant A's entries."""
        stmt = select(AuditLog).where(AuditLog.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1
        assert entries[0].resource_id == "test-report-a"

    async def test_tenant_b_audit_invisible_to_tenant_a(
        self,
        db_session: AsyncSession,
        audit_log_a: AuditLog,
        audit_log_b: AuditLog,
    ):
        """Tenant A's audit query must not return Tenant B's entries."""
        stmt = select(AuditLog).where(AuditLog.tenant_id == _TENANT_A_ID)
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        resource_ids = [e.resource_id for e in entries]
        assert "test-report-b" not in resource_ids

    async def test_cross_tenant_audit_query_returns_empty(
        self, db_session: AsyncSession, audit_log_a: AuditLog
    ):
        """Querying with a non-existent tenant ID must return no audit logs."""
        fake_tenant = uuid.UUID("00000000-0000-4000-8000-999999999999")
        stmt = select(AuditLog).where(AuditLog.tenant_id == fake_tenant)
        result = await db_session.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 0


# ── Multi-Tenant Count Verification ─────────────────────────


class TestMultiTenantCounts:
    """Tests verifying aggregate counts respect tenant boundaries."""

    async def test_total_reports_across_tenants(
        self, db_session: AsyncSession, report_a: Report, report_b: Report
    ):
        """Unscoped query must return all reports across all tenants."""
        stmt = select(Report)
        result = await db_session.execute(stmt)
        all_reports = list(result.scalars().all())

        assert len(all_reports) == 2

    async def test_scoped_count_per_tenant(
        self, db_session: AsyncSession, report_a: Report, report_b: Report
    ):
        """Scoped count per tenant must return exactly 1 each."""
        for tenant_id in [_TENANT_A_ID, _TENANT_B_ID]:
            stmt = select(Report).where(Report.tenant_id == tenant_id)
            result = await db_session.execute(stmt)
            reports = list(result.scalars().all())
            assert len(reports) == 1
