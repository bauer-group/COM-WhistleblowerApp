"""Hinweisgebersystem -- Report Business Logic Tests.

Tests:
- Report creation with encrypted fields and case number generation.
- Passphrase hash verification for mailbox authentication.
- Status workflow transitions (valid and invalid).
- LkSG extended fields handling.
- Retention period calculation (3yr HinSchG, 7yr LkSG).
- Case number format and uniqueness.
- Deadline calculation (7-day confirmation, 3-month feedback).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.report import (
    Channel,
    LkSGCategory,
    Priority,
    Report,
    ReporterRelationship,
    ReportStatus,
    SupplyChainTier,
)
from app.schemas.report import ReportCreate
from app.services.report_service import (
    ReportService,
    _CASE_NUMBER_LENGTH,
    _CONFIRMATION_DEADLINE_DAYS,
    _DEFAULT_RETENTION_HINSCHG_YEARS,
    _DEFAULT_RETENTION_LKSG_YEARS,
    _FEEDBACK_DEADLINE_DAYS,
    _VALID_TRANSITIONS,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def tenant_id():
    """Return a deterministic test tenant UUID."""
    return uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture()
def mock_report_repo():
    """Create a mocked ReportRepository."""
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_by_case_number = AsyncMock(return_value=None)
    repo.update = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    repo.get_overdue_reports = AsyncMock(return_value=[])
    repo.count_by_status = AsyncMock(return_value={})
    return repo


@pytest.fixture()
def mock_audit_repo():
    """Create a mocked AuditRepository."""
    repo = AsyncMock()
    repo.log = AsyncMock()
    repo.insert = AsyncMock()
    return repo


@pytest.fixture()
def report_service(db_session, tenant_id, mock_report_repo, mock_audit_repo):
    """Create a ReportService with mocked repositories."""
    service = ReportService(db_session, tenant_id)
    service._report_repo = mock_report_repo
    service._audit_repo = mock_audit_repo
    return service


@pytest.fixture()
def sample_report_data():
    """Return valid HinSchG report creation data."""
    return ReportCreate(
        subject="Suspected fraud in accounting",
        description="I observed irregular transactions in Q3 2025.",
        channel=Channel.HINSCHG,
        is_anonymous=True,
        language="de",
    )


@pytest.fixture()
def sample_lksg_report_data():
    """Return valid LkSG report creation data with extended fields."""
    return ReportCreate(
        subject="Child labour violations at supplier",
        description="Children under 14 working at the factory floor.",
        channel=Channel.LKSG,
        is_anonymous=True,
        language="en",
        country="DEU",
        organization="Supplier GmbH",
        supply_chain_tier=SupplyChainTier.DIRECT_SUPPLIER,
        reporter_relationship=ReporterRelationship.NGO,
        lksg_category=LkSGCategory.CHILD_LABOR,
    )


@pytest.fixture()
def sample_report(tenant_id):
    """Return a persisted-style Report instance for update/transition tests."""
    now = datetime.now(timezone.utc)
    return Report(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        case_number="HWS-ABCDEFGHIJKL",
        passphrase_hash="$2b$12$fakehashedpassphrase",
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


# ── Case Number Generation ──────────────────────────────────


class TestCaseNumberGeneration:
    """Tests for case number format and generation."""

    async def test_case_number_format(self, report_service, mock_report_repo):
        """Case number must start with 'HWS-' followed by 12 alphanumeric chars."""
        mock_report_repo.get_by_case_number.return_value = None
        case_number = await report_service._generate_unique_case_number()

        assert case_number.startswith("HWS-")
        assert len(case_number) == _CASE_NUMBER_LENGTH
        # Remaining 12 chars are uppercase alphanumeric
        suffix = case_number[4:]
        assert suffix.isalnum()
        assert suffix == suffix.upper()

    async def test_case_number_uniqueness(self, report_service, mock_report_repo):
        """Multiple generated case numbers must all be unique."""
        mock_report_repo.get_by_case_number.return_value = None
        numbers = set()
        for _ in range(20):
            cn = await report_service._generate_unique_case_number()
            numbers.add(cn)
        assert len(numbers) == 20

    async def test_case_number_retry_on_collision(
        self, report_service, mock_report_repo, sample_report
    ):
        """Generator must retry when a collision is detected."""
        # First call returns existing (collision), second call returns None
        mock_report_repo.get_by_case_number.side_effect = [
            sample_report,
            None,
        ]
        case_number = await report_service._generate_unique_case_number()

        assert case_number.startswith("HWS-")
        assert mock_report_repo.get_by_case_number.call_count == 2


# ── Report Creation ─────────────────────────────────────────


class TestReportCreation:
    """Tests for report creation with encrypted fields."""

    async def test_create_report_returns_case_number(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Creating a report must return a case number."""
        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = lambda r: r

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            result = await report_service.create_report(sample_report_data)

        assert result.case_number is not None
        assert result.case_number.startswith("HWS-")
        assert len(result.case_number) == _CASE_NUMBER_LENGTH

    async def test_create_report_generates_passphrase(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Report created without password must return a passphrase."""
        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = lambda r: r

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ), patch(
            "app.services.report_service.generate_passphrase",
            return_value="ocean brick maple verify abstract notable",
        ):
            result = await report_service.create_report(sample_report_data)

        assert result.passphrase == "ocean brick maple verify abstract notable"

    async def test_create_report_with_password_no_passphrase(
        self, report_service, mock_report_repo
    ):
        """When reporter provides a password, no passphrase is returned."""
        data = ReportCreate(
            subject="Test report",
            description="Description",
            channel=Channel.HINSCHG,
            is_anonymous=True,
            password="MySecurePassword123!",
        )
        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = lambda r: r

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            result = await report_service.create_report(data)

        assert result.passphrase is None

    async def test_create_report_sets_encrypted_fields(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Encrypted fields must be set on the Report model."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        assert created_report is not None
        assert created_report.subject_encrypted == sample_report_data.subject
        assert created_report.description_encrypted == sample_report_data.description

    async def test_create_report_non_anonymous_sets_identity(
        self, report_service, mock_report_repo
    ):
        """Non-anonymous reports must store encrypted reporter identity."""
        data = ReportCreate(
            subject="Non-anonymous report",
            description="Details here",
            channel=Channel.HINSCHG,
            is_anonymous=False,
            reporter_name="Jane Doe",
            reporter_email="jane@example.com",
            reporter_phone="+491234567890",
        )
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(data)

        assert created_report.reporter_name_encrypted == "Jane Doe"
        assert created_report.reporter_email_encrypted == "jane@example.com"
        assert created_report.reporter_phone_encrypted == "+491234567890"

    async def test_create_report_audit_logged(
        self, report_service, mock_report_repo, mock_audit_repo, sample_report_data
    ):
        """Creating a report must produce an audit log entry."""
        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = lambda r: r

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        mock_audit_repo.log.assert_called_once()
        call_kwargs = mock_audit_repo.log.call_args.kwargs
        assert call_kwargs["actor_type"] == "reporter"
        assert call_kwargs["resource_type"] == "report"


# ── Passphrase Verification ─────────────────────────────────


class TestPassphraseVerification:
    """Tests for mailbox authentication via passphrase hash."""

    async def test_authenticate_mailbox_valid(
        self, report_service, mock_report_repo, mock_audit_repo, sample_report
    ):
        """Valid case_number + passphrase must return the report."""
        mock_report_repo.get_by_case_number.return_value = sample_report

        with patch(
            "app.services.report_service.verify_password",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await report_service.authenticate_mailbox(
                "HWS-ABCDEFGHIJKL",
                "ocean brick maple verify abstract notable",
            )

        assert result is not None
        assert result.case_number == "HWS-ABCDEFGHIJKL"

    async def test_authenticate_mailbox_wrong_passphrase(
        self, report_service, mock_report_repo, mock_audit_repo, sample_report
    ):
        """Wrong passphrase must return None and log failure."""
        mock_report_repo.get_by_case_number.return_value = sample_report

        with patch(
            "app.services.report_service.verify_password",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await report_service.authenticate_mailbox(
                "HWS-ABCDEFGHIJKL",
                "wrong passphrase words here six total",
            )

        assert result is None
        # Failed login should be logged
        mock_audit_repo.log.assert_called()

    async def test_authenticate_mailbox_unknown_case(
        self, report_service, mock_report_repo
    ):
        """Unknown case number must return None (timing-safe)."""
        mock_report_repo.get_by_case_number.return_value = None

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
        ):
            result = await report_service.authenticate_mailbox(
                "HWS-NONEXISTENT0",
                "some passphrase",
            )

        assert result is None


# ── Status Workflow Transitions ─────────────────────────────


class TestStatusWorkflow:
    """Tests for HinSchG status transitions."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (ReportStatus.EINGEGANGEN, ReportStatus.IN_PRUEFUNG),
            (ReportStatus.IN_PRUEFUNG, ReportStatus.IN_BEARBEITUNG),
            (ReportStatus.IN_PRUEFUNG, ReportStatus.ABGESCHLOSSEN),
            (ReportStatus.IN_BEARBEITUNG, ReportStatus.RUECKMELDUNG),
            (ReportStatus.IN_BEARBEITUNG, ReportStatus.ABGESCHLOSSEN),
            (ReportStatus.RUECKMELDUNG, ReportStatus.IN_BEARBEITUNG),
            (ReportStatus.RUECKMELDUNG, ReportStatus.ABGESCHLOSSEN),
        ],
    )
    def test_valid_transition(self, current: ReportStatus, target: ReportStatus):
        """All legal transitions per HinSchG workflow must be accepted."""
        # Must not raise
        ReportService._validate_status_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (ReportStatus.EINGEGANGEN, ReportStatus.IN_BEARBEITUNG),
            (ReportStatus.EINGEGANGEN, ReportStatus.RUECKMELDUNG),
            (ReportStatus.EINGEGANGEN, ReportStatus.ABGESCHLOSSEN),
            (ReportStatus.IN_PRUEFUNG, ReportStatus.EINGEGANGEN),
            (ReportStatus.IN_BEARBEITUNG, ReportStatus.EINGEGANGEN),
            (ReportStatus.IN_BEARBEITUNG, ReportStatus.IN_PRUEFUNG),
            (ReportStatus.RUECKMELDUNG, ReportStatus.EINGEGANGEN),
            (ReportStatus.RUECKMELDUNG, ReportStatus.IN_PRUEFUNG),
            (ReportStatus.ABGESCHLOSSEN, ReportStatus.EINGEGANGEN),
            (ReportStatus.ABGESCHLOSSEN, ReportStatus.IN_PRUEFUNG),
            (ReportStatus.ABGESCHLOSSEN, ReportStatus.IN_BEARBEITUNG),
            (ReportStatus.ABGESCHLOSSEN, ReportStatus.RUECKMELDUNG),
        ],
    )
    def test_invalid_transition_raises(
        self, current: ReportStatus, target: ReportStatus
    ):
        """Illegal transitions must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid status transition"):
            ReportService._validate_status_transition(current, target)

    def test_abgeschlossen_is_terminal(self):
        """ABGESCHLOSSEN must be a terminal status (no outgoing transitions)."""
        assert _VALID_TRANSITIONS[ReportStatus.ABGESCHLOSSEN] == set()

    def test_all_statuses_have_transition_entry(self):
        """Every ReportStatus must have an entry in the transitions map."""
        for status in ReportStatus:
            assert status in _VALID_TRANSITIONS

    async def test_transition_status_updates_report(
        self, report_service, mock_report_repo, mock_audit_repo, sample_report
    ):
        """transition_status must call repo update with the new status."""
        mock_report_repo.get_by_id.return_value = sample_report
        mock_report_repo.update.return_value = sample_report

        await report_service.transition_status(
            report_id=sample_report.id,
            new_status=ReportStatus.IN_PRUEFUNG,
            expected_version=1,
            actor_id=uuid.uuid4(),
        )

        mock_report_repo.update.assert_called_once()
        call_kwargs = mock_report_repo.update.call_args.kwargs
        assert call_kwargs["status"] == ReportStatus.IN_PRUEFUNG

    async def test_transition_status_logs_audit(
        self, report_service, mock_report_repo, mock_audit_repo, sample_report
    ):
        """Status transitions must be recorded in the audit trail."""
        mock_report_repo.get_by_id.return_value = sample_report
        mock_report_repo.update.return_value = sample_report

        await report_service.transition_status(
            report_id=sample_report.id,
            new_status=ReportStatus.IN_PRUEFUNG,
            expected_version=1,
            actor_id=uuid.uuid4(),
        )

        mock_audit_repo.log.assert_called_once()
        call_kwargs = mock_audit_repo.log.call_args.kwargs
        assert call_kwargs["details"]["old_status"] == "eingegangen"
        assert call_kwargs["details"]["new_status"] == "in_pruefung"


# ── LkSG Extended Fields ───────────────────────────────────


class TestLkSGExtendedFields:
    """Tests for LkSG-specific data fields."""

    async def test_lksg_report_stores_extended_fields(
        self, report_service, mock_report_repo, sample_lksg_report_data
    ):
        """LkSG reports must store country, org, tier, relationship, category."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_lksg_report_data)

        assert created_report is not None
        assert created_report.channel == Channel.LKSG
        assert created_report.country == "DEU"
        assert created_report.organization == "Supplier GmbH"
        assert created_report.supply_chain_tier == SupplyChainTier.DIRECT_SUPPLIER
        assert created_report.reporter_relationship == ReporterRelationship.NGO
        assert created_report.lksg_category == LkSGCategory.CHILD_LABOR

    async def test_hinschg_report_no_lksg_fields(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """HinSchG reports must not set LkSG-extended fields."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        assert created_report.country is None
        assert created_report.organization is None
        assert created_report.supply_chain_tier is None


# ── Retention Period Calculation ─────────────────────────────


class TestRetentionPeriod:
    """Tests for HinSchG (3yr) and LkSG (7yr) retention calculation."""

    def test_hinschg_default_retention_3_years(self):
        """HinSchG reports must default to 3-year retention."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        retention = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
        )
        expected = now + timedelta(days=365 * _DEFAULT_RETENTION_HINSCHG_YEARS)
        assert retention == expected

    def test_lksg_default_retention_7_years(self):
        """LkSG reports must default to 7-year retention."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        retention = ReportService._calculate_retention(
            channel=Channel.LKSG,
            created_at=now,
        )
        expected = now + timedelta(days=365 * _DEFAULT_RETENTION_LKSG_YEARS)
        assert retention == expected

    def test_tenant_config_override_hinschg(self):
        """Tenant config must be able to override HinSchG retention."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        config = {"retention_hinschg_years": 5}
        retention = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
            tenant_config=config,
        )
        expected = now + timedelta(days=365 * 5)
        assert retention == expected

    def test_tenant_config_override_lksg(self):
        """Tenant config must be able to override LkSG retention."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        config = {"retention_lksg_years": 10}
        retention = ReportService._calculate_retention(
            channel=Channel.LKSG,
            created_at=now,
            tenant_config=config,
        )
        expected = now + timedelta(days=365 * 10)
        assert retention == expected


# ── Deadline Calculation ────────────────────────────────────


class TestDeadlineCalculation:
    """Tests for HinSchG §28 deadline calculation on creation."""

    async def test_confirmation_deadline_7_days(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Reports must get a confirmation deadline of 7 days."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        assert created_report.confirmation_deadline is not None
        # Deadline should be approximately 7 days from now
        delta = created_report.confirmation_deadline - created_report.created_at
        assert abs(delta.days - _CONFIRMATION_DEADLINE_DAYS) <= 1

    async def test_feedback_deadline_90_days(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Reports must get a feedback deadline of ~90 days (3 months)."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        assert created_report.feedback_deadline is not None
        delta = created_report.feedback_deadline - created_report.created_at
        assert abs(delta.days - _FEEDBACK_DEADLINE_DAYS) <= 1

    async def test_initial_status_eingegangen(
        self, report_service, mock_report_repo, sample_report_data
    ):
        """Newly created reports must have EINGEGANGEN status."""
        created_report = None

        async def capture_report(r):
            nonlocal created_report
            created_report = r
            return r

        mock_report_repo.get_by_case_number.return_value = None
        mock_report_repo.create.side_effect = capture_report

        with patch(
            "app.services.report_service.hash_password",
            new_callable=AsyncMock,
            return_value="$2b$12$hashed",
        ):
            await report_service.create_report(sample_report_data)

        assert created_report.status == ReportStatus.EINGEGANGEN
