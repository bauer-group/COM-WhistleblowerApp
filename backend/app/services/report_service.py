"""Hinweisgebersystem -- Report (Case) Business Service.

Orchestrates all report lifecycle operations including:
- **Creation**: case number generation, passphrase generation with
  bcrypt hashing, channel-specific field handling (HinSchG vs LkSG),
  deadline calculation, retention period assignment.
- **Status workflow**: legal transitions between the five case statuses
  (eingegangen -> in_pruefung -> in_bearbeitung -> rueckmeldung ->
  abgeschlossen) with validation.
- **Updates**: status transitions, priority changes, assignment, and
  category updates -- all with optimistic locking.
- **Retrieval**: single report by ID/case-number, paginated lists with
  filters, and mailbox-specific views.
- **KPI statistics**: counts by status for the admin dashboard.
- **Authentication**: passphrase/password verification for mailbox
  access.

The service delegates all database access to ``ReportRepository`` and
all audit logging to ``AuditRepository``.  Sensitive fields are passed
through to the ORM layer where ``PGPString`` handles transparent
encryption via pgcrypto.

Usage::

    from app.services.report_service import ReportService

    service = ReportService(session, tenant_id)
    result = await service.create_report(data)
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passphrase import generate_passphrase
from app.core.security import hash_password, verify_password
from app.middleware.anonymity import round_timestamp
from app.models.audit_log import AuditAction
from app.models.report import (
    Channel,
    Priority,
    Report,
    ReportStatus,
)
from app.repositories.audit_repo import AuditRepository
from app.repositories.report_repo import ReportRepository
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.report import ReportCreate, ReportCreateResponse, ReportUpdate

logger = structlog.get_logger(__name__)

# ── Case number generation ───────────────────────────────────
# 16 alphanumeric uppercase characters (~95 bits of entropy).

_CASE_NUMBER_LENGTH = 16
_CASE_NUMBER_ALPHABET = string.ascii_uppercase + string.digits

# ── Status workflow transitions ──────────────────────────────
# Legal transitions per §28 HinSchG workflow:
#   eingegangen -> in_pruefung -> in_bearbeitung -> rueckmeldung -> abgeschlossen
# Allow backwards transition from rueckmeldung to in_bearbeitung
# for cases that need further investigation after feedback.

_VALID_TRANSITIONS: dict[ReportStatus, set[ReportStatus]] = {
    ReportStatus.EINGEGANGEN: {ReportStatus.IN_PRUEFUNG},
    ReportStatus.IN_PRUEFUNG: {
        ReportStatus.IN_BEARBEITUNG,
        ReportStatus.ABGESCHLOSSEN,
    },
    ReportStatus.IN_BEARBEITUNG: {
        ReportStatus.RUECKMELDUNG,
        ReportStatus.ABGESCHLOSSEN,
    },
    ReportStatus.RUECKMELDUNG: {
        ReportStatus.IN_BEARBEITUNG,
        ReportStatus.ABGESCHLOSSEN,
    },
    ReportStatus.ABGESCHLOSSEN: set(),
}

# ── Retention periods ────────────────────────────────────────
# HinSchG: 3 years, LkSG: 7 years (configurable per tenant).

_DEFAULT_RETENTION_HINSCHG_YEARS = 3
_DEFAULT_RETENTION_LKSG_YEARS = 7

# ── HinSchG deadlines ───────────────────────────────────────
# §28 HinSchG: confirmation within 7 days, feedback within 3 months.

_CONFIRMATION_DEADLINE_DAYS = 7
_FEEDBACK_DEADLINE_DAYS = 90  # ~3 months


class ReportService:
    """Business logic for whistleblower reports / cases.

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
        self._report_repo = ReportRepository(session)
        self._audit_repo = AuditRepository(session)

    # ── Create ────────────────────────────────────────────────

    async def create_report(
        self,
        data: ReportCreate,
        *,
        tenant_config: dict | None = None,
    ) -> ReportCreateResponse:
        """Create a new whistleblower report.

        Generates a unique case number, creates a passphrase (or uses
        the reporter's self-chosen password), hashes the credential
        with bcrypt, calculates deadlines and retention period, and
        persists the report.

        Parameters
        ----------
        data:
            Validated report creation schema from the API layer.
        tenant_config:
            Optional tenant configuration dict for custom retention
            periods.  Falls back to statutory defaults if not provided.

        Returns
        -------
        ReportCreateResponse
            Contains the case number and passphrase (only shown once).
        """
        # Generate unique 16-char case number
        case_number = await self._generate_unique_case_number()

        # Generate or accept credential
        plain_passphrase: str | None = None
        if data.password:
            # Reporter chose their own password
            credential_hash = await hash_password(data.password)
        else:
            # Generate 6-word BIP-39 passphrase
            plain_passphrase = generate_passphrase()
            credential_hash = await hash_password(plain_passphrase)

        # Calculate deadlines (HinSchG §28)
        now = datetime.now(timezone.utc)
        if data.is_anonymous:
            now = round_timestamp(now)
        confirmation_deadline = now + timedelta(days=_CONFIRMATION_DEADLINE_DAYS)
        feedback_deadline = now + timedelta(days=_FEEDBACK_DEADLINE_DAYS)

        # Calculate retention period
        retention_until = self._calculate_retention(
            channel=data.channel,
            created_at=now,
            tenant_config=tenant_config,
        )

        # Build the report model
        report = Report(
            tenant_id=self._tenant_id,
            case_number=case_number,
            passphrase_hash=credential_hash,
            is_anonymous=data.is_anonymous,
            channel=data.channel,
            status=ReportStatus.EINGEGANGEN,
            priority=Priority.MEDIUM,
            category=data.category,
            language=data.language,
            created_at=now,  # Rounded for anonymous, exact for non-anonymous
            confirmation_deadline=confirmation_deadline,
            feedback_deadline=feedback_deadline,
            retention_until=retention_until,
        )

        # Set encrypted fields (PGPString handles encryption at ORM level)
        report.subject_encrypted = data.subject  # type: ignore[assignment]
        report.description_encrypted = data.description  # type: ignore[assignment]

        # Reporter identity (non-anonymous only)
        if not data.is_anonymous:
            report.reporter_name_encrypted = data.reporter_name  # type: ignore[assignment]
            report.reporter_email_encrypted = data.reporter_email  # type: ignore[assignment]
            report.reporter_phone_encrypted = data.reporter_phone  # type: ignore[assignment]

        # LkSG-extended fields
        if data.channel == Channel.LKSG:
            report.country = data.country
            report.organization = data.organization
            report.supply_chain_tier = data.supply_chain_tier
            report.reporter_relationship = data.reporter_relationship
            report.lksg_category = data.lksg_category

        # Persist
        report = await self._report_repo.create(report)

        # Audit log
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.CASE_CREATED,
            resource_type="report",
            resource_id=str(report.id),
            actor_type="reporter",
            details={
                "case_number": case_number,
                "channel": data.channel.value,
                "is_anonymous": data.is_anonymous,
            },
        )

        logger.info(
            "report_created",
            case_number=case_number,
            channel=data.channel.value,
            is_anonymous=data.is_anonymous,
        )

        # Return partial response; the API layer adds the access_token.
        return ReportCreateResponse(
            case_number=case_number,
            report_id=str(report.id),
            passphrase=plain_passphrase,
            access_token="",  # placeholder — filled by API layer
            message="Report submitted successfully.",
        )

    # ── Read (single) ─────────────────────────────────────────

    async def get_report_by_id(
        self,
        report_id: uuid.UUID,
        *,
        with_messages: bool = False,
        with_attachments: bool = False,
    ) -> Report | None:
        """Fetch a single report by ID.

        RLS ensures tenant isolation.  Returns ``None`` if not found.
        """
        return await self._report_repo.get_by_id(
            report_id,
            with_messages=with_messages,
            with_attachments=with_attachments,
        )

    async def get_report_by_case_number(
        self,
        case_number: str,
        *,
        with_messages: bool = False,
        with_attachments: bool = False,
    ) -> Report | None:
        """Fetch a single report by case number.

        This is the primary lookup for the reporter mailbox.
        """
        return await self._report_repo.get_by_case_number(
            case_number,
            with_messages=with_messages,
            with_attachments=with_attachments,
        )

    # ── Read (list) ───────────────────────────────────────────

    async def list_reports(
        self,
        *,
        pagination: PaginationParams,
        status: ReportStatus | None = None,
        priority: Priority | None = None,
        channel: Channel | None = None,
        category: str | None = None,
        assigned_to: uuid.UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        overdue_only: bool = False,
        sort_by: str = "created_at",
        sort_desc: bool = True,
    ) -> tuple[list[Report], PaginationMeta]:
        """List reports with filtering, search, and pagination.

        Delegates to the repository with all filter parameters.
        """
        return await self._report_repo.list_paginated(
            pagination=pagination,
            status=status,
            priority=priority,
            channel=channel,
            category=category,
            assigned_to=assigned_to,
            search=search,
            date_from=date_from,
            date_to=date_to,
            overdue_only=overdue_only,
            sort_by=sort_by,
            sort_desc=sort_desc,
        )

    # ── Update ────────────────────────────────────────────────

    async def update_report(
        self,
        report_id: uuid.UUID,
        data: ReportUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Report | None:
        """Update report metadata with optimistic locking.

        Validates status transitions and logs changes to the audit
        trail.  Returns ``None`` if the report is not found or an
        optimistic lock conflict occurs.

        Parameters
        ----------
        report_id:
            UUID of the report to update.
        data:
            Validated update schema.
        actor_id:
            UUID of the user performing the update (for audit trail).
        """
        # Fetch current state for validation
        current = await self._report_repo.get_by_id(report_id)
        if current is None:
            return None

        # Prepare update fields
        update_fields: dict[str, Any] = {}

        # Status transition validation
        if data.status is not None and data.status != current.status:
            self._validate_status_transition(current.status, data.status)
            update_fields["status"] = data.status

            # Audit status change
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.CASE_STATUS_CHANGED,
                resource_type="report",
                resource_id=str(report_id),
                actor_id=actor_id,
                actor_type="user",
                details={
                    "old_status": current.status.value,
                    "new_status": data.status.value,
                },
            )

        # Priority change
        if data.priority is not None and data.priority != current.priority:
            update_fields["priority"] = data.priority

            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.CASE_PRIORITY_CHANGED,
                resource_type="report",
                resource_id=str(report_id),
                actor_id=actor_id,
                actor_type="user",
                details={
                    "old_priority": current.priority.value,
                    "new_priority": data.priority.value,
                },
            )

        # Assignment change
        if data.assigned_to is not None and data.assigned_to != current.assigned_to:
            update_fields["assigned_to"] = data.assigned_to

            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.CASE_ASSIGNED,
                resource_type="report",
                resource_id=str(report_id),
                actor_id=actor_id,
                actor_type="user",
                details={
                    "assigned_to": str(data.assigned_to),
                },
            )

        # Category change
        if data.category is not None:
            update_fields["category"] = data.category

        # Sub-status handling — when the main status changes and no
        # explicit sub_status_id is provided, clear the sub-status
        # (it belonged to the old status).  Explicit sub_status_id
        # always takes precedence.
        if "sub_status_id" in data.model_fields_set and data.sub_status_id:
            from app.models.substatus import SubStatus  # noqa: PLC0415

            substatus = await self._report_repo._session.get(
                SubStatus, data.sub_status_id
            )
            target_status = update_fields.get("status", current.status)
            if not substatus or substatus.parent_status != target_status:
                raise ValueError(
                    f"Sub-status does not belong to status '{target_status.value}'."
                )
            update_fields["sub_status_id"] = data.sub_status_id
        elif "sub_status_id" in data.model_fields_set:
            # Explicitly set to None → clear the sub-status
            update_fields["sub_status_id"] = data.sub_status_id
        elif "status" in update_fields:
            # Main status changed without explicit sub-status → clear
            update_fields["sub_status_id"] = None

        # Related case numbers
        if data.related_case_numbers is not None:
            update_fields["related_case_numbers"] = data.related_case_numbers

        if not update_fields:
            return current

        return await self._report_repo.update(
            report_id,
            expected_version=data.version,
            **update_fields,
        )

    async def transition_status(
        self,
        report_id: uuid.UUID,
        new_status: ReportStatus,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Report | None:
        """Transition a report to a new status.

        Validates the transition and records it in the audit trail.
        Returns ``None`` on not found or optimistic lock conflict.

        Parameters
        ----------
        report_id:
            UUID of the report.
        new_status:
            Target status.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the acting user.
        """
        current = await self._report_repo.get_by_id(report_id)
        if current is None:
            return None

        self._validate_status_transition(current.status, new_status)

        updated = await self._report_repo.update(
            report_id,
            expected_version=expected_version,
            status=new_status,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.CASE_STATUS_CHANGED,
                resource_type="report",
                resource_id=str(report_id),
                actor_id=actor_id,
                actor_type="user",
                details={
                    "old_status": current.status.value,
                    "new_status": new_status.value,
                },
            )

        return updated

    async def assign_handler(
        self,
        report_id: uuid.UUID,
        handler_id: uuid.UUID,
        *,
        expected_version: int,
        actor_id: uuid.UUID | None = None,
    ) -> Report | None:
        """Assign a handler to a report.

        Parameters
        ----------
        report_id:
            UUID of the report.
        handler_id:
            UUID of the user to assign.
        expected_version:
            Current version for optimistic locking.
        actor_id:
            UUID of the user making the assignment.
        """
        updated = await self._report_repo.update(
            report_id,
            expected_version=expected_version,
            assigned_to=handler_id,
        )

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.CASE_ASSIGNED,
                resource_type="report",
                resource_id=str(report_id),
                actor_id=actor_id,
                actor_type="user",
                details={"assigned_to": str(handler_id)},
            )

        return updated

    # ── Confirmation / Feedback tracking ─────────────────────

    async def mark_confirmation_sent(
        self,
        report_id: uuid.UUID,
        *,
        expected_version: int,
    ) -> Report | None:
        """Record that the 7-day confirmation was sent."""
        return await self._report_repo.update(
            report_id,
            expected_version=expected_version,
            confirmation_sent_at=datetime.now(timezone.utc),
        )

    async def mark_feedback_sent(
        self,
        report_id: uuid.UUID,
        *,
        expected_version: int,
    ) -> Report | None:
        """Record that the 3-month feedback was sent."""
        return await self._report_repo.update(
            report_id,
            expected_version=expected_version,
            feedback_sent_at=datetime.now(timezone.utc),
        )

    # ── Delete (retention) ───────────────────────────────────

    async def delete_report(
        self,
        report_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        reason: str = "data_retention",
    ) -> bool:
        """Delete a report (used by data retention task).

        Logs the deletion to the audit trail before removing the data.

        Returns ``True`` if the report was deleted, ``False`` if not
        found.
        """
        report = await self._report_repo.get_by_id(report_id)
        if report is None:
            return False

        # Audit before deletion (data will be gone after)
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.CASE_DELETED,
            resource_type="report",
            resource_id=str(report_id),
            actor_id=actor_id,
            actor_type="system" if actor_id is None else "user",
            details={
                "case_number": report.case_number,
                "reason": reason,
            },
        )

        return await self._report_repo.delete(report_id)

    # ── Mailbox authentication ───────────────────────────────

    async def authenticate_mailbox(
        self,
        case_number: str,
        credential: str,
    ) -> Report | None:
        """Authenticate a reporter for mailbox access.

        Looks up the report by case number and verifies the provided
        credential (passphrase or self-chosen password) against the
        stored bcrypt hash.

        Parameters
        ----------
        case_number:
            The 16-character case identifier.
        credential:
            The passphrase or self-chosen password.

        Returns
        -------
        Report | None
            The report if authentication succeeds, ``None`` otherwise.
        """
        report = await self._report_repo.get_by_case_number(case_number)
        if report is None:
            # Perform a dummy hash to prevent timing attacks
            await hash_password("dummy_password_for_timing")
            logger.warning(
                "mailbox_login_case_not_found",
                case_number=case_number,
            )
            return None

        is_valid = await verify_password(credential, report.passphrase_hash)

        if not is_valid:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.MAILBOX_LOGIN_FAILED,
                resource_type="report",
                resource_id=str(report.id),
                actor_type="reporter",
                details={"case_number": case_number},
            )
            logger.warning(
                "mailbox_login_failed",
                case_number=case_number,
            )
            return None

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.MAILBOX_LOGIN,
            resource_type="report",
            resource_id=str(report.id),
            actor_type="reporter",
            details={"case_number": case_number},
        )

        return report

    # ── KPI statistics ───────────────────────────────────────

    async def get_kpi_statistics(self) -> dict[str, Any]:
        """Return KPI statistics for the admin dashboard.

        Returns
        -------
        dict
            Dictionary with:
            - ``by_status``: report count per status.
            - ``total``: total report count.
            - ``overdue_count``: number of overdue reports.
        """
        by_status = await self._report_repo.count_by_status()
        total = sum(by_status.values())
        overdue_reports = await self._report_repo.get_overdue_reports()

        return {
            "by_status": by_status,
            "total": total,
            "overdue_count": len(overdue_reports),
        }

    # ── Overdue / retention queries ──────────────────────────

    async def get_overdue_reports(self) -> list[Report]:
        """Fetch reports with overdue confirmation or feedback deadlines."""
        return await self._report_repo.get_overdue_reports()

    async def get_expired_reports(self) -> list[Report]:
        """Fetch reports past their retention date for auto-deletion."""
        return await self._report_repo.get_expired_reports()

    # ── Private helpers ──────────────────────────────────────

    async def _generate_unique_case_number(self) -> str:
        """Generate a unique 16-character alphanumeric case number.

        Checks for collisions in the database (astronomically unlikely
        but required for correctness).  Format: ``HWS-XXXXXXXXXXXX``
        where ``X`` is alphanumeric uppercase.
        """
        for _ in range(10):  # Max retries for collision avoidance
            random_part = "".join(
                secrets.choice(_CASE_NUMBER_ALPHABET)
                for _ in range(_CASE_NUMBER_LENGTH - 4)  # 12 random chars
            )
            case_number = f"HWS-{random_part}"

            # Check uniqueness
            existing = await self._report_repo.get_by_case_number(case_number)
            if existing is None:
                return case_number

        # Should never happen with 36^12 possible combinations
        raise RuntimeError("Unable to generate unique case number after 10 attempts.")

    @staticmethod
    def _validate_status_transition(
        current: ReportStatus,
        target: ReportStatus,
    ) -> None:
        """Validate that a status transition is legal.

        Raises
        ------
        ValueError
            If the transition is not permitted.
        """
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid status transition: {current.value} -> {target.value}. "
                f"Allowed transitions from {current.value}: "
                f"{', '.join(s.value for s in allowed) or 'none'}."
            )

    @staticmethod
    def _calculate_retention(
        *,
        channel: Channel,
        created_at: datetime,
        tenant_config: dict | None = None,
    ) -> datetime:
        """Calculate the retention-until date for a report.

        Per HinSchG: 3 years from case closure (approximated from
        creation + 3 years).  Per LkSG: 7 years.  Tenant config can
        override the defaults.

        Parameters
        ----------
        channel:
            The reporting channel.
        created_at:
            Report creation timestamp.
        tenant_config:
            Tenant configuration dict with optional
            ``retention_hinschg_years`` and ``retention_lksg_years``.
        """
        config = tenant_config or {}

        if channel == Channel.LKSG:
            years = config.get(
                "retention_lksg_years",
                _DEFAULT_RETENTION_LKSG_YEARS,
            )
        else:
            years = config.get(
                "retention_hinschg_years",
                _DEFAULT_RETENTION_HINSCHG_YEARS,
            )

        return created_at + timedelta(days=365 * years)
