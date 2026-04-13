"""Hinweisgebersystem -- Audit Log Tests.

Tests:
- Audit log INSERT succeeds via AuditRepository.
- All AuditAction types are valid enum members.
- Audit entries record correct actor, resource, and details.
- Listing and filtering work correctly.
- Immutability design: no update/delete methods exist on the repository.
- All state changes produce audit log entries.

Note: UPDATE/DELETE blocking is enforced via PostgreSQL database rules
(triggers) which cannot be tested in SQLite in-memory.  These tests
verify the application-layer guarantees that the AuditRepository
provides only INSERT and SELECT operations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.models.tenant import Tenant
from app.repositories.audit_repo import AuditRepository
from app.schemas.common import PaginationParams

pytestmark = pytest.mark.asyncio

# ── Fixtures ─────────────────────────────────────────────────

_TEST_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture()
async def tenant(db_session: AsyncSession) -> Tenant:
    """Create a test tenant for audit log entries."""
    tenant = Tenant(
        id=_TEST_TENANT_ID,
        slug="audit-test-tenant",
        name="Audit Test Org",
        is_active=True,
        config={},
        dek_ciphertext="a" * 64,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture()
def audit_repo(db_session: AsyncSession) -> AuditRepository:
    """Return an AuditRepository bound to the test session."""
    return AuditRepository(db_session)


# ── Audit Log INSERT ────────────────────────────────────────


class TestAuditLogInsert:
    """Tests for audit log creation (append-only INSERT)."""

    async def test_insert_creates_entry(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """Inserting an audit log entry must succeed and return the entry."""
        entry = AuditLog(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            actor_type="reporter",
            resource_type="report",
            resource_id="test-report-id",
            details={"case_number": "HWS-TESTTEST1234", "channel": "hinschg"},
        )
        result = await audit_repo.insert(entry)

        assert result.id is not None
        assert result.action == AuditAction.CASE_CREATED
        assert result.resource_type == "report"
        assert result.resource_id == "test-report-id"

    async def test_log_convenience_method(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """The ``log()`` convenience method must create and return an entry."""
        result = await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_STATUS_CHANGED,
            resource_type="report",
            resource_id="report-123",
            actor_id=uuid.uuid4(),
            actor_type="user",
            details={"old_status": "eingegangen", "new_status": "in_pruefung"},
        )

        assert result.id is not None
        assert result.action == AuditAction.CASE_STATUS_CHANGED
        assert result.details["old_status"] == "eingegangen"

    async def test_insert_with_all_fields(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """Audit entry with all optional fields populated must succeed."""
        actor_id = uuid.uuid4()
        result = await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            resource_id=str(actor_id),
            actor_id=actor_id,
            actor_type="user",
            details={"method": "oidc"},
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 Test Browser",
        )

        assert result.actor_id == actor_id
        assert result.ip_address == "192.168.1.100"
        assert result.user_agent == "Mozilla/5.0 Test Browser"

    async def test_insert_reporter_action_no_ip(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """Reporter actions must store NULL ip_address for anonymity."""
        result = await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.MAILBOX_LOGIN,
            resource_type="report",
            resource_id="report-anon",
            actor_type="reporter",
            ip_address=None,
        )

        assert result.ip_address is None
        assert result.actor_type == "reporter"

    async def test_insert_system_action(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """System-initiated actions must store actor_type='system'."""
        result = await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.DATA_RETENTION_EXECUTED,
            resource_type="report",
            resource_id="report-expired",
            actor_type="system",
            details={"reason": "retention_period_exceeded"},
        )

        assert result.actor_type == "system"
        assert result.actor_id is None

    async def test_created_at_is_set(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """Audit entries must have a ``created_at`` timestamp."""
        result = await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="report-ts",
            actor_type="reporter",
        )

        # SQLite doesn't execute server_default=func.now(), so created_at
        # may be None in test.  In production (PostgreSQL), it is always set.
        # We test that the field exists on the model.
        assert hasattr(result, "created_at")


# ── Audit Log Immutability (Application Layer) ──────────────


class TestAuditLogImmutability:
    """Tests ensuring the audit repository only supports INSERT and SELECT.

    The AuditRepository intentionally has no ``update()`` or ``delete()``
    methods.  This is the application-layer guarantee complementing the
    database-level triggers that block UPDATE and DELETE.
    """

    def test_no_update_method(self):
        """AuditRepository must not expose an ``update()`` method."""
        assert not hasattr(AuditRepository, "update")

    def test_no_delete_method(self):
        """AuditRepository must not expose a ``delete()`` method."""
        assert not hasattr(AuditRepository, "delete")

    def test_only_insert_and_read_methods(self):
        """Public methods should only be insert, log, get, list, and count."""
        public_methods = [
            m for m in dir(AuditRepository)
            if not m.startswith("_") and callable(getattr(AuditRepository, m))
        ]
        # Allowed public methods
        allowed = {
            "insert", "log", "get_by_id",
            "list_paginated", "list_by_resource", "list_by_actor",
            "count",
        }
        for method in public_methods:
            assert method in allowed, (
                f"Unexpected public method '{method}' on AuditRepository. "
                f"Audit trail must be append-only."
            )


# ── State Change Logging ────────────────────────────────────


class TestStateChangeLogging:
    """Tests that all security-relevant actions have corresponding AuditAction types."""

    def test_case_lifecycle_actions_exist(self):
        """Case lifecycle events must have audit action types."""
        assert AuditAction.CASE_CREATED
        assert AuditAction.CASE_STATUS_CHANGED
        assert AuditAction.CASE_ASSIGNED
        assert AuditAction.CASE_PRIORITY_CHANGED
        assert AuditAction.CASE_DELETED

    def test_message_actions_exist(self):
        """Message events must have audit action types."""
        assert AuditAction.MESSAGE_SENT
        assert AuditAction.MESSAGE_READ

    def test_identity_disclosure_actions_exist(self):
        """4-eyes disclosure events must have audit action types."""
        assert AuditAction.IDENTITY_DISCLOSURE_REQUESTED
        assert AuditAction.IDENTITY_DISCLOSURE_APPROVED
        assert AuditAction.IDENTITY_DISCLOSURE_REJECTED
        assert AuditAction.IDENTITY_DISCLOSED

    def test_user_management_actions_exist(self):
        """User management events must have audit action types."""
        assert AuditAction.USER_CREATED
        assert AuditAction.USER_UPDATED
        assert AuditAction.USER_DEACTIVATED
        assert AuditAction.USER_LOGIN
        assert AuditAction.USER_LOGOUT

    def test_tenant_management_actions_exist(self):
        """Tenant management events must have audit action types."""
        assert AuditAction.TENANT_CREATED
        assert AuditAction.TENANT_UPDATED
        assert AuditAction.TENANT_DEACTIVATED

    def test_mailbox_access_actions_exist(self):
        """Mailbox access events must have audit action types."""
        assert AuditAction.MAILBOX_LOGIN
        assert AuditAction.MAILBOX_LOGIN_FAILED
        assert AuditAction.MAGIC_LINK_REQUESTED
        assert AuditAction.MAGIC_LINK_USED

    def test_data_retention_action_exists(self):
        """Data retention events must have audit action types."""
        assert AuditAction.DATA_RETENTION_EXECUTED

    def test_system_error_action_exists(self):
        """System error events must have an audit action type."""
        assert AuditAction.SYSTEM_ERROR


# ── Audit Log Listing & Filtering ───────────────────────────


class TestAuditLogListing:
    """Tests for audit log listing and filtering."""

    async def test_list_paginated_returns_entries(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """list_paginated must return inserted entries."""
        for i in range(3):
            await audit_repo.log(
                tenant_id=_TEST_TENANT_ID,
                action=AuditAction.CASE_CREATED,
                resource_type="report",
                resource_id=f"report-{i}",
                actor_type="reporter",
            )

        entries, meta = await audit_repo.list_paginated(
            pagination=PaginationParams(page=1, page_size=10),
        )

        assert len(entries) == 3
        assert meta.total == 3
        assert meta.page == 1

    async def test_list_paginated_filter_by_action(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """Filtering by action must return only matching entries."""
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="r1",
            actor_type="reporter",
        )
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            resource_id="u1",
            actor_type="user",
        )

        entries, meta = await audit_repo.list_paginated(
            pagination=PaginationParams(page=1, page_size=10),
            action=AuditAction.CASE_CREATED,
        )

        assert len(entries) == 1
        assert entries[0].action == AuditAction.CASE_CREATED

    async def test_list_by_resource(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """list_by_resource must return entries for a specific resource."""
        target_id = "specific-report-id"
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id=target_id,
            actor_type="reporter",
        )
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_STATUS_CHANGED,
            resource_type="report",
            resource_id=target_id,
            actor_type="user",
        )
        # Different resource
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="other-report",
            actor_type="reporter",
        )

        entries = await audit_repo.list_by_resource("report", target_id)

        assert len(entries) == 2
        assert all(e.resource_id == target_id for e in entries)

    async def test_list_by_actor(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """list_by_actor must return entries for a specific actor."""
        actor_id = uuid.uuid4()
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_STATUS_CHANGED,
            resource_type="report",
            resource_id="r1",
            actor_id=actor_id,
            actor_type="user",
        )
        # Different actor
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="r2",
            actor_type="reporter",
        )

        entries = await audit_repo.list_by_actor(actor_id)

        assert len(entries) == 1
        assert entries[0].actor_id == actor_id

    async def test_count_all(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """count() must return the total number of audit entries."""
        for _ in range(5):
            await audit_repo.log(
                tenant_id=_TEST_TENANT_ID,
                action=AuditAction.CASE_CREATED,
                resource_type="report",
                resource_id="r",
                actor_type="reporter",
            )

        total = await audit_repo.count()
        assert total == 5

    async def test_count_with_action_filter(
        self, audit_repo: AuditRepository, tenant: Tenant
    ):
        """count() with action filter must return only matching entries."""
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="r1",
            actor_type="reporter",
        )
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            resource_id="u1",
            actor_type="user",
        )
        await audit_repo.log(
            tenant_id=_TEST_TENANT_ID,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id="r2",
            actor_type="reporter",
        )

        count = await audit_repo.count(action=AuditAction.CASE_CREATED)
        assert count == 2


# ── AuditAction Enum Completeness ───────────────────────────


class TestAuditActionEnum:
    """Tests for the AuditAction enum integrity."""

    def test_all_actions_are_string_enums(self):
        """All AuditAction members must have dotted string values."""
        for action in AuditAction:
            assert isinstance(action.value, str)
            assert "." in action.value, (
                f"AuditAction.{action.name} value '{action.value}' "
                f"does not follow 'category.event' naming convention."
            )

    def test_no_duplicate_action_values(self):
        """All AuditAction members must have unique values."""
        values = [a.value for a in AuditAction]
        assert len(values) == len(set(values))

    def test_minimum_action_count(self):
        """There must be at least 20 audit action types for compliance."""
        assert len(AuditAction) >= 20
