"""Hinweisgebersystem -- Background Task Scheduler.

Configures APScheduler v3 ``AsyncIOScheduler`` with three recurring
background jobs:

- **deadline_checker**: runs daily at 06:00 UTC.  Scans all active
  tenants for reports with overdue 7-day confirmation or 3-month
  feedback deadlines (HinSchG §28) and triggers email notifications
  to the assigned handler or tenant administrators.

- **data_retention**: runs daily at 03:00 UTC.  Deletes reports whose
  per-row ``retention_until`` date has passed (3 years HinSchG,
  7 years LkSG), along with their attachments in MinIO.  All
  deletions are logged in the audit trail.

- **email_worker**: runs every 30 seconds.  Drains the Redis email
  queue and delivers messages via SMTP with exponential backoff
  (3 retries).  Sends an escalation alert after final failure.

Lifecycle:
    Call ``start_scheduler()`` during application startup and
    ``shutdown_scheduler()`` during shutdown (from the FastAPI lifespan
    context manager).

Usage::

    from app.tasks import start_scheduler, shutdown_scheduler

    # In FastAPI lifespan:
    start_scheduler()
    yield
    shutdown_scheduler()

.. important::
   This module uses **APScheduler v3** (``AsyncIOScheduler``).
   APScheduler v4 has a completely different API and is NOT compatible.
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.tasks.data_retention import run_data_retention
from app.tasks.deadline_checker import run_deadline_checker
from app.tasks.email_worker import run_email_worker

logger = structlog.get_logger(__name__)

# ── Module-level scheduler instance ──────────────────────────

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the current scheduler instance.

    Raises
    ------
    RuntimeError
        If the scheduler has not been started yet.
    """
    if _scheduler is None:
        raise RuntimeError(
            "Scheduler not initialised. Call start_scheduler() first."
        )
    return _scheduler


def start_scheduler() -> None:
    """Create, configure, and start the APScheduler instance.

    Registers all three background jobs with their respective
    triggers.  The scheduler runs inside the existing asyncio event
    loop (``AsyncIOScheduler``).
    """
    global _scheduler  # noqa: PLW0603

    _scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,  # 1 hour
        },
    )

    # ── Deadline checker: daily at 06:00 UTC ─────────────────
    _scheduler.add_job(
        run_deadline_checker,
        trigger="cron",
        hour=6,
        minute=0,
        id="deadline_checker",
        name="HinSchG deadline checker (7-day confirmation, 3-month feedback)",
        replace_existing=True,
    )

    # ── Data retention: daily at 03:00 UTC ───────────────────
    _scheduler.add_job(
        run_data_retention,
        trigger="cron",
        hour=3,
        minute=0,
        id="data_retention",
        name="Data retention (auto-delete expired reports)",
        replace_existing=True,
    )

    # ── Email worker: every 30 seconds ───────────────────────
    _scheduler.add_job(
        run_email_worker,
        trigger="interval",
        seconds=30,
        id="email_worker",
        name="Async email queue processor (Redis)",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "scheduler_started",
        jobs=[job.id for job in _scheduler.get_jobs()],
    )


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler.

    Waits for currently running jobs to finish before stopping.
    """
    global _scheduler  # noqa: PLW0603

    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        logger.info("scheduler_stopped")
    _scheduler = None
