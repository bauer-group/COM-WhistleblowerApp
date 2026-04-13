"""Hinweisgebersystem -- Data Retention Background Task.

Runs daily to enforce statutory data retention rules:

- **HinSchG**: reports must be deleted 3 years after creation
  (configurable per tenant via ``retention_hinschg_years``).
- **LkSG**: reports must be deleted 7 years after creation
  (configurable per tenant via ``retention_lksg_years``).

The retention period is calculated per report at creation time and
stored in the ``retention_until`` column.  This task queries for
all reports where ``retention_until < NOW()`` and deletes them.

Deletion includes:
1. All associated attachments removed from MinIO storage.
2. Audit log entry for each deletion (``data_retention.executed``).
3. Database cascade removes messages, attachments metadata, and
   identity disclosures.

.. note::
   The audit log entries themselves are NOT deleted — they are
   append-only and must be preserved for compliance purposes.
   The audit entry records the case number and deletion reason
   before the report data is removed.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text

from app.core.database import get_session_factory
from app.core.storage import get_storage
from app.models.audit_log import AuditAction
from app.repositories.audit_repo import AuditRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.tenant_repo import TenantRepository

logger = structlog.get_logger(__name__)


async def run_data_retention() -> None:
    """Delete all reports that have exceeded their retention period.

    Iterates over all active tenants, queries for expired reports,
    removes their attachments from MinIO, and deletes the reports
    from the database.

    This function is designed to be called by APScheduler and never
    raises — all errors are caught, logged, and the run continues.
    """
    logger.info("data_retention_started")
    session_factory = get_session_factory()

    deleted_total = 0
    tenants_processed = 0

    try:
        # Fetch all active tenants (unscoped session)
        async with session_factory() as session:
            tenant_repo = TenantRepository(session)
            tenants = await tenant_repo.list_all_active()
            await session.commit()
    except Exception:
        logger.error("data_retention_tenant_fetch_failed", exc_info=True)
        return

    for tenant in tenants:
        try:
            deleted = await _process_tenant_retention(
                session_factory=session_factory,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
            )
            deleted_total += deleted
            tenants_processed += 1
        except Exception:
            logger.error(
                "data_retention_tenant_failed",
                tenant_id=str(tenant.id),
                tenant_slug=tenant.slug,
                exc_info=True,
            )

    logger.info(
        "data_retention_completed",
        tenants_processed=tenants_processed,
        reports_deleted=deleted_total,
    )


async def _process_tenant_retention(
    *,
    session_factory: object,
    tenant_id: object,
    tenant_slug: str,
) -> int:
    """Process data retention for a single tenant.

    Parameters
    ----------
    session_factory:
        Async session factory (from ``get_session_factory()``).
    tenant_id:
        UUID of the tenant.
    tenant_slug:
        Tenant slug for logging context.

    Returns
    -------
    int
        Number of reports deleted.
    """
    deleted_count = 0

    async with session_factory() as session:
        # Set RLS context for this tenant
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )

        report_repo = ReportRepository(session)
        audit_repo = AuditRepository(session)

        expired_reports = await report_repo.get_expired_reports()

        if not expired_reports:
            return 0

        logger.info(
            "data_retention_processing",
            tenant_slug=tenant_slug,
            expired_count=len(expired_reports),
        )

        for report in expired_reports:
            try:
                # Remove attachments from MinIO storage
                await _delete_report_attachments(report)

                # Audit before deletion (data is gone after)
                await audit_repo.log(
                    tenant_id=tenant_id,
                    action=AuditAction.DATA_RETENTION_EXECUTED,
                    resource_type="report",
                    resource_id=str(report.id),
                    actor_type="system",
                    details={
                        "case_number": report.case_number,
                        "channel": report.channel.value,
                        "retention_until": (
                            report.retention_until.isoformat()
                            if report.retention_until
                            else None
                        ),
                        "reason": "statutory_retention_period_expired",
                    },
                )

                # Delete the report (cascade deletes messages, attachments
                # metadata, identity disclosures)
                deleted = await report_repo.delete(report.id)

                if deleted:
                    deleted_count += 1
                    logger.info(
                        "data_retention_report_deleted",
                        case_number=report.case_number,
                        channel=report.channel.value,
                        tenant_slug=tenant_slug,
                    )

            except Exception:
                logger.error(
                    "data_retention_report_failed",
                    case_number=report.case_number,
                    tenant_slug=tenant_slug,
                    exc_info=True,
                )

        await session.commit()

    return deleted_count


async def _delete_report_attachments(report: object) -> None:
    """Delete all attachments from MinIO storage for a report.

    Silently ignores missing objects (already deleted or never
    uploaded) and logs individual deletion failures without raising.

    Parameters
    ----------
    report:
        The ``Report`` ORM instance with eagerly loaded attachments.
    """
    try:
        storage = get_storage()
    except RuntimeError:
        logger.warning(
            "data_retention_storage_unavailable",
            case_number=report.case_number,
        )
        return

    for attachment in getattr(report, "attachments", []):
        if not attachment.storage_key:
            continue

        try:
            await storage.delete(attachment.storage_key)
            logger.debug(
                "data_retention_attachment_deleted",
                storage_key=attachment.storage_key,
                case_number=report.case_number,
            )
        except Exception:
            logger.error(
                "data_retention_attachment_delete_failed",
                storage_key=attachment.storage_key,
                case_number=report.case_number,
                exc_info=True,
            )
