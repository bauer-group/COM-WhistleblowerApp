"""Hinweisgebersystem -- Deadline Checker Background Task.

Runs daily to identify reports with overdue HinSchG §28 deadlines:

- **7-day confirmation deadline**: the internal reporting office must
  confirm receipt within 7 calendar days.  If ``confirmation_deadline``
  has passed and ``confirmation_sent_at`` is still ``None``, the
  assigned handler (or tenant administrators) are notified.

- **3-month feedback deadline**: the reporter must receive feedback on
  the measures taken within 3 months (~90 days).  If
  ``feedback_deadline`` has passed and ``feedback_sent_at`` is still
  ``None``, the assigned handler is notified.

The task iterates over all active tenants, creates an RLS-scoped
database session for each, and queries for overdue reports using
``ReportRepository.get_overdue_reports()``.  Notifications are sent
via ``NotificationService.send_deadline_warning()``.

.. note::
   This task never raises exceptions to the caller.  All errors are
   logged and the task continues with the next tenant / report.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from app.core.database import get_session_factory
from app.models.report import Report, ReportStatus
from app.models.user import UserRole
from app.repositories.report_repo import ReportRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.services.notification_service import NotificationService

logger = structlog.get_logger(__name__)


async def run_deadline_checker() -> None:
    """Check all active tenants for reports with overdue deadlines.

    For each overdue report, a ``deadline_warning`` notification is
    sent to the assigned handler.  If no handler is assigned, the
    notification goes to all active tenant administrators.

    This function is designed to be called by APScheduler and never
    raises — all errors are caught, logged, and the run continues.
    """
    logger.info("deadline_checker_started")
    session_factory = get_session_factory()

    checked_count = 0
    notified_count = 0

    try:
        # Fetch all active tenants (unscoped session)
        async with session_factory() as session:
            tenant_repo = TenantRepository(session)
            tenants = await tenant_repo.list_all_active()
            await session.commit()
    except Exception:
        logger.error("deadline_checker_tenant_fetch_failed", exc_info=True)
        return

    for tenant in tenants:
        try:
            notified = await _check_tenant_deadlines(
                session_factory=session_factory,
                tenant_id=tenant.id,
                tenant_config=tenant.config,
            )
            checked_count += 1
            notified_count += notified
        except Exception:
            logger.error(
                "deadline_checker_tenant_failed",
                tenant_id=str(tenant.id),
                tenant_slug=tenant.slug,
                exc_info=True,
            )

    logger.info(
        "deadline_checker_completed",
        tenants_checked=checked_count,
        notifications_sent=notified_count,
    )


async def _check_tenant_deadlines(
    *,
    session_factory: object,
    tenant_id: object,
    tenant_config: dict | None,
) -> int:
    """Check a single tenant's reports for overdue deadlines.

    Parameters
    ----------
    session_factory:
        Async session factory (from ``get_session_factory()``).
    tenant_id:
        UUID of the tenant to check.
    tenant_config:
        Tenant configuration dict (for SMTP overrides).

    Returns
    -------
    int
        Number of notifications sent.
    """
    notified = 0
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # Set RLS context for this tenant
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        report_repo = ReportRepository(session)
        user_repo = UserRepository(session)
        notification_service = NotificationService(tenant_config=tenant_config)

        overdue_reports = await report_repo.get_overdue_reports()

        for report in overdue_reports:
            # Skip closed cases
            if report.status == ReportStatus.ABGESCHLOSSEN:
                continue

            # Determine which deadlines are overdue
            deadlines_overdue = _identify_overdue_deadlines(report, now)

            if not deadlines_overdue:
                continue

            # Find recipients: assigned handler, or all tenant admins
            recipients = await _get_notification_recipients(
                report=report,
                user_repo=user_repo,
            )

            for recipient_email in recipients:
                for deadline_type, days_overdue in deadlines_overdue:
                    try:
                        await notification_service.send_deadline_warning(
                            to=recipient_email,
                            case_number=report.case_number,
                            deadline_type=deadline_type,
                            days_remaining=-days_overdue,
                            language=report.language or "de",
                        )
                        notified += 1
                        logger.info(
                            "deadline_warning_sent",
                            case_number=report.case_number,
                            deadline_type=deadline_type,
                            days_overdue=days_overdue,
                            recipient=recipient_email,
                        )
                    except Exception:
                        logger.error(
                            "deadline_warning_send_failed",
                            case_number=report.case_number,
                            deadline_type=deadline_type,
                            recipient=recipient_email,
                            exc_info=True,
                        )

        await session.commit()

    return notified


def _identify_overdue_deadlines(
    report: Report,
    now: datetime,
) -> list[tuple[str, int]]:
    """Identify which deadlines are overdue for a report.

    Returns
    -------
    list[tuple[str, int]]
        List of ``(deadline_type_label, days_overdue)`` tuples.
    """
    overdue: list[tuple[str, int]] = []

    # 7-day confirmation deadline
    if (
        report.confirmation_deadline is not None
        and report.confirmation_sent_at is None
        and report.confirmation_deadline < now
    ):
        days = (now - report.confirmation_deadline).days
        overdue.append(("Eingangsbestätigung (7 Tage)", days))

    # 3-month feedback deadline
    if (
        report.feedback_deadline is not None
        and report.feedback_sent_at is None
        and report.feedback_deadline < now
    ):
        days = (now - report.feedback_deadline).days
        overdue.append(("Rückmeldung (3 Monate)", days))

    return overdue


async def _get_notification_recipients(
    *,
    report: Report,
    user_repo: UserRepository,
) -> list[str]:
    """Determine who should receive deadline warning notifications.

    Priority:
    1. The assigned handler (if present and active).
    2. All active tenant admins + system admins (fallback).

    Returns
    -------
    list[str]
        Email addresses of notification recipients.
    """
    # Try assigned handler first
    if report.assigned_to is not None:
        handler = await user_repo.get_by_id(report.assigned_to)
        if handler is not None and handler.is_active:
            return [handler.email]

    # Fall back to all handlers (includes system_admin, tenant_admin, handler)
    handlers = await user_repo.list_handlers()
    if handlers:
        return [h.email for h in handlers]

    logger.warning(
        "deadline_no_recipients",
        case_number=report.case_number,
    )
    return []
