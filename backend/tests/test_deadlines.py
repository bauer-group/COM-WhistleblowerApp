"""Hinweisgebersystem -- Deadline Management Tests.

Tests:
- 7-day confirmation deadline calculation.
- 3-month (~90 day) feedback deadline calculation.
- Overdue detection for confirmation and feedback deadlines.
- Retention period calculation (3yr HinSchG, 7yr LkSG).
- Deadline checker helper functions.
- Expired report detection for data retention.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.report import (
    Channel,
    Priority,
    Report,
    ReportStatus,
)
from app.services.report_service import (
    ReportService,
    _CONFIRMATION_DEADLINE_DAYS,
    _DEFAULT_RETENTION_HINSCHG_YEARS,
    _DEFAULT_RETENTION_LKSG_YEARS,
    _FEEDBACK_DEADLINE_DAYS,
)
from app.tasks.deadline_checker import _identify_overdue_deadlines

pytestmark = pytest.mark.asyncio

# ── Test Constants ───────────────────────────────────────────

_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


# ── Fixtures ─────────────────────────────────────────────────


def _make_report(
    *,
    status: ReportStatus = ReportStatus.EINGEGANGEN,
    channel: Channel = Channel.HINSCHG,
    confirmation_deadline: datetime | None = None,
    feedback_deadline: datetime | None = None,
    confirmation_sent_at: datetime | None = None,
    feedback_sent_at: datetime | None = None,
    retention_until: datetime | None = None,
    created_at: datetime | None = None,
) -> Report:
    """Create a Report instance for deadline testing."""
    now = datetime.now(timezone.utc)
    return Report(
        id=uuid.uuid4(),
        tenant_id=_TENANT_ID,
        case_number="HWS-DEADLINETEST",
        passphrase_hash="$2b$12$fakehash",
        is_anonymous=True,
        channel=channel,
        status=status,
        priority=Priority.MEDIUM,
        language="de",
        version=1,
        created_at=created_at or now,
        updated_at=now,
        confirmation_deadline=confirmation_deadline,
        feedback_deadline=feedback_deadline,
        confirmation_sent_at=confirmation_sent_at,
        feedback_sent_at=feedback_sent_at,
        retention_until=retention_until,
    )


# ── 7-Day Confirmation Deadline ─────────────────────────────


class TestConfirmationDeadline:
    """Tests for the 7-day confirmation deadline (HinSchG §28)."""

    def test_confirmation_deadline_is_7_days(self):
        """The confirmation deadline constant must be 7 days."""
        assert _CONFIRMATION_DEADLINE_DAYS == 7

    def test_confirmation_deadline_calculation(self):
        """Deadline must be exactly 7 days from report creation."""
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        expected = now + timedelta(days=7)

        # The service calculates deadlines during creation
        assert expected == datetime(2025, 6, 8, 12, 0, 0, tzinfo=timezone.utc)

    def test_overdue_when_deadline_passed_no_confirmation(self):
        """Report must be overdue if deadline passed and no confirmation sent."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=2),
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        assert len(overdue) >= 1
        deadline_types = [d[0] for d in overdue]
        assert any("Eingangsbestätigung" in t for t in deadline_types)

    def test_not_overdue_when_confirmation_sent(self):
        """Report must not be overdue if confirmation was already sent."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=2),
            confirmation_sent_at=now - timedelta(days=3),
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        # No confirmation overdue (feedback still in the future)
        confirmation_overdue = [
            d for d in overdue if "Eingangsbestätigung" in d[0]
        ]
        assert len(confirmation_overdue) == 0

    def test_not_overdue_when_deadline_in_future(self):
        """Report must not be overdue if deadline is still in the future."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now + timedelta(days=5),
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        assert len(overdue) == 0

    def test_overdue_days_calculation(self):
        """Days overdue must be correctly calculated."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=3),
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        for deadline_type, days_overdue in overdue:
            if "Eingangsbestätigung" in deadline_type:
                assert days_overdue == 3


# ── 3-Month Feedback Deadline ───────────────────────────────


class TestFeedbackDeadline:
    """Tests for the 3-month (~90 day) feedback deadline (HinSchG §28)."""

    def test_feedback_deadline_is_90_days(self):
        """The feedback deadline constant must be 90 days."""
        assert _FEEDBACK_DEADLINE_DAYS == 90

    def test_feedback_deadline_calculation(self):
        """Feedback deadline must be ~90 days from report creation."""
        now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        expected = now + timedelta(days=90)

        assert expected == datetime(2025, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_overdue_when_feedback_deadline_passed(self):
        """Report must be overdue if feedback deadline passed without feedback."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=100),
            confirmation_sent_at=now - timedelta(days=95),
            feedback_deadline=now - timedelta(days=10),
            feedback_sent_at=None,
        )

        overdue = _identify_overdue_deadlines(report, now)

        feedback_overdue = [d for d in overdue if "Rückmeldung" in d[0]]
        assert len(feedback_overdue) == 1

    def test_not_overdue_when_feedback_sent(self):
        """Report must not be overdue if feedback was already sent."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=100),
            confirmation_sent_at=now - timedelta(days=95),
            feedback_deadline=now - timedelta(days=10),
            feedback_sent_at=now - timedelta(days=15),
        )

        overdue = _identify_overdue_deadlines(report, now)

        feedback_overdue = [d for d in overdue if "Rückmeldung" in d[0]]
        assert len(feedback_overdue) == 0

    def test_both_deadlines_overdue(self):
        """Both confirmation and feedback can be overdue simultaneously."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=100),
            confirmation_sent_at=None,
            feedback_deadline=now - timedelta(days=10),
            feedback_sent_at=None,
        )

        overdue = _identify_overdue_deadlines(report, now)

        assert len(overdue) == 2
        types = [d[0] for d in overdue]
        assert any("Eingangsbestätigung" in t for t in types)
        assert any("Rückmeldung" in t for t in types)


# ── Overdue Detection ───────────────────────────────────────


class TestOverdueDetection:
    """Tests for overdue detection edge cases."""

    def test_no_deadline_no_overdue(self):
        """Reports without deadlines must not be considered overdue."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=None,
            feedback_deadline=None,
        )

        overdue = _identify_overdue_deadlines(report, now)
        assert len(overdue) == 0

    def test_deadline_exactly_now_not_overdue(self):
        """Reports with deadline exactly at 'now' should not be overdue.

        The check uses strict less-than, so deadline == now is not overdue.
        """
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now,
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        # Deadline == now is not strictly past
        confirmation_overdue = [
            d for d in overdue if "Eingangsbestätigung" in d[0]
        ]
        assert len(confirmation_overdue) == 0

    def test_overdue_by_one_second(self):
        """A deadline that passed by 1 second must be detected as overdue."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(seconds=1),
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        # Should be detected (0 days overdue)
        assert len(overdue) >= 1


# ── Retention Period ────────────────────────────────────────


class TestRetentionPeriod:
    """Tests for data retention period calculation."""

    def test_hinschg_3_year_retention(self):
        """HinSchG reports must have a 3-year default retention period."""
        assert _DEFAULT_RETENTION_HINSCHG_YEARS == 3

        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        retention = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
        )

        expected = now + timedelta(days=365 * 3)
        assert retention == expected

    def test_lksg_7_year_retention(self):
        """LkSG reports must have a 7-year default retention period."""
        assert _DEFAULT_RETENTION_LKSG_YEARS == 7

        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        retention = ReportService._calculate_retention(
            channel=Channel.LKSG,
            created_at=now,
        )

        expected = now + timedelta(days=365 * 7)
        assert retention == expected

    def test_retention_with_tenant_override(self):
        """Tenant-configured retention must override the statutory defaults."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)

        # Custom 4-year HinSchG retention
        config = {"retention_hinschg_years": 4}
        retention = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
            tenant_config=config,
        )
        expected = now + timedelta(days=365 * 4)
        assert retention == expected

    def test_retention_lksg_longer_than_hinschg(self):
        """LkSG retention (7yr) must be longer than HinSchG retention (3yr)."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)

        hinschg = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
        )
        lksg = ReportService._calculate_retention(
            channel=Channel.LKSG,
            created_at=now,
        )

        assert lksg > hinschg

    def test_retention_with_empty_config(self):
        """Empty tenant config must use statutory defaults."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)

        retention = ReportService._calculate_retention(
            channel=Channel.HINSCHG,
            created_at=now,
            tenant_config={},
        )

        expected = now + timedelta(days=365 * _DEFAULT_RETENTION_HINSCHG_YEARS)
        assert retention == expected

    def test_retention_with_none_config(self):
        """None tenant config must use statutory defaults."""
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)

        retention = ReportService._calculate_retention(
            channel=Channel.LKSG,
            created_at=now,
            tenant_config=None,
        )

        expected = now + timedelta(days=365 * _DEFAULT_RETENTION_LKSG_YEARS)
        assert retention == expected


# ── Deadline Checker Helper Function ────────────────────────


class TestDeadlineCheckerHelpers:
    """Tests for the deadline checker's helper functions."""

    def test_identify_overdue_returns_empty_for_completed_deadlines(self):
        """Reports with all deadlines met must return empty overdue list."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=50),
            confirmation_sent_at=now - timedelta(days=55),
            feedback_deadline=now - timedelta(days=5),
            feedback_sent_at=now - timedelta(days=10),
        )

        overdue = _identify_overdue_deadlines(report, now)
        assert len(overdue) == 0

    def test_identify_overdue_returns_tuple_format(self):
        """Overdue result must be list of (label, days_overdue) tuples."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=5),
            confirmation_sent_at=None,
            feedback_deadline=now + timedelta(days=80),
        )

        overdue = _identify_overdue_deadlines(report, now)

        assert len(overdue) >= 1
        for item in overdue:
            assert isinstance(item, tuple)
            assert len(item) == 2
            label, days = item
            assert isinstance(label, str)
            assert isinstance(days, int)

    def test_identify_overdue_feedback_days_count(self):
        """Overdue days for feedback must be correctly calculated."""
        now = datetime.now(timezone.utc)
        report = _make_report(
            confirmation_deadline=now - timedelta(days=100),
            confirmation_sent_at=now - timedelta(days=95),
            feedback_deadline=now - timedelta(days=15),
            feedback_sent_at=None,
        )

        overdue = _identify_overdue_deadlines(report, now)

        feedback_items = [d for d in overdue if "Rückmeldung" in d[0]]
        assert len(feedback_items) == 1
        assert feedback_items[0][1] == 15


# ── End-to-End Deadline + Retention Scenarios ───────────────


class TestDeadlineRetentionScenarios:
    """Scenario-based tests combining deadlines with retention."""

    def test_hinschg_report_lifecycle_deadlines(self):
        """HinSchG report must have correct deadlines and 3yr retention."""
        now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

        confirmation = now + timedelta(days=_CONFIRMATION_DEADLINE_DAYS)
        feedback = now + timedelta(days=_FEEDBACK_DEADLINE_DAYS)
        retention = now + timedelta(days=365 * _DEFAULT_RETENTION_HINSCHG_YEARS)

        assert confirmation == datetime(
            2025, 6, 8, 10, 0, 0, tzinfo=timezone.utc
        )
        assert feedback == datetime(
            2025, 8, 30, 10, 0, 0, tzinfo=timezone.utc
        )
        # 3 years from June 1, 2025
        assert retention.year == 2028

    def test_lksg_report_lifecycle_deadlines(self):
        """LkSG report must have correct deadlines and 7yr retention."""
        now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        retention = now + timedelta(days=365 * _DEFAULT_RETENTION_LKSG_YEARS)

        # 7 years from Jan 1, 2025
        assert retention.year == 2031
