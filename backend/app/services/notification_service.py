"""Hinweisgebersystem -- Notification Business Service.

Email orchestration service for all system notifications.  Provides a
single entry point for the backend to send notifications without
worrying about SMTP configuration, template rendering, or per-tenant
overrides.

Supported notification types:
- **report_confirmation**: sent to the reporter after submission.
- **new_message**: sent when a new message is added to the mailbox.
- **status_change**: sent when the case status changes.
- **case_assignment**: sent to the handler when a case is assigned.
- **deadline_warning**: sent when a deadline is approaching.
- **magic_link**: sent for passwordless reporter authentication.

Features:
- Per-tenant SMTP configuration override (from ``tenants.config.smtp``).
- Language-specific email templates (DE / EN).
- Fire-and-forget delivery: SMTP failures are logged but never raise
  to the caller, so notifications do not break business logic.
- All email bodies contain **only links** -- no sensitive case content.

Usage::

    from app.services.notification_service import NotificationService

    service = NotificationService(tenant_config=tenant.config)
    await service.send_report_confirmation(
        to="reporter@example.com",
        case_number="HWS-ABC123456789",
        language="de",
    )
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.config import get_settings
from app.core.smtp import send_templated_email

logger = structlog.get_logger(__name__)


class NotificationService:
    """Email notification orchestration service.

    Wraps :func:`app.core.smtp.send_templated_email` with
    business-level methods for each notification type.  Automatically
    resolves per-tenant SMTP configuration and constructs the required
    template context (portal URL, admin URL, etc.).

    Parameters
    ----------
    tenant_config:
        Optional tenant configuration dict (from ``tenant.config``).
        If the dict contains a ``"smtp"`` key, its value is used as
        per-tenant SMTP override.  If ``None``, the global SMTP config
        is used.
    """

    def __init__(
        self,
        tenant_config: dict[str, Any] | None = None,
    ) -> None:
        self._tenant_smtp = (
            tenant_config.get("smtp") if tenant_config else None
        )
        self._settings = get_settings()

    # ── Report confirmation ──────────────────────────────────────

    async def send_report_confirmation(
        self,
        *,
        to: str,
        case_number: str,
        language: str = "de",
    ) -> None:
        """Send a report confirmation email to the reporter.

        Sent immediately after a new report is submitted.  Contains the
        case number and a link to the secure mailbox (per HinSchG §28:
        confirmation within 7 days).

        Parameters
        ----------
        to:
            Reporter's email address.
        case_number:
            The 16-character case identifier.
        language:
            ISO 639-1 language code (``"de"`` or ``"en"``).
        """
        portal_url = f"{self._settings.app_base_url}/mailbox"
        context = {
            "case_number": case_number,
            "portal_url": portal_url,
        }
        await self._send_safe(
            to=to,
            template="report_confirmation",
            context=context,
            language=language,
        )

    # ── New message notification ─────────────────────────────────

    async def send_new_message_notification(
        self,
        *,
        to: str,
        case_number: str,
        language: str = "de",
    ) -> None:
        """Notify the reporter about a new message in their mailbox.

        Parameters
        ----------
        to:
            Reporter's email address.
        case_number:
            The 16-character case identifier.
        language:
            ISO 639-1 language code.
        """
        portal_url = f"{self._settings.app_base_url}/mailbox"
        context = {
            "case_number": case_number,
            "portal_url": portal_url,
        }
        await self._send_safe(
            to=to,
            template="new_message",
            context=context,
            language=language,
        )

    # ── Status change notification ───────────────────────────────

    async def send_status_change_notification(
        self,
        *,
        to: str,
        case_number: str,
        language: str = "de",
    ) -> None:
        """Notify the reporter about a status change on their case.

        Parameters
        ----------
        to:
            Reporter's email address.
        case_number:
            The 16-character case identifier.
        language:
            ISO 639-1 language code.
        """
        portal_url = f"{self._settings.app_base_url}/mailbox"
        context = {
            "case_number": case_number,
            "portal_url": portal_url,
        }
        await self._send_safe(
            to=to,
            template="status_change",
            context=context,
            language=language,
        )

    # ── Case assignment notification ─────────────────────────────

    async def send_case_assignment_notification(
        self,
        *,
        to: str,
        case_number: str,
        language: str = "de",
    ) -> None:
        """Notify a handler that a case has been assigned to them.

        Parameters
        ----------
        to:
            Handler's email address.
        case_number:
            The 16-character case identifier.
        language:
            ISO 639-1 language code.
        """
        admin_url = f"{self._settings.app_base_url}/admin/cases"
        context = {
            "case_number": case_number,
            "admin_url": admin_url,
        }
        await self._send_safe(
            to=to,
            template="case_assignment",
            context=context,
            language=language,
        )

    # ── Deadline warning notification ────────────────────────────

    async def send_deadline_warning(
        self,
        *,
        to: str,
        case_number: str,
        deadline_type: str,
        days_remaining: int,
        language: str = "de",
    ) -> None:
        """Warn a handler about an approaching deadline.

        Parameters
        ----------
        to:
            Handler's email address.
        case_number:
            The 16-character case identifier.
        deadline_type:
            Human-readable deadline label, e.g.
            ``"Eingangsbestätigung"`` or ``"Rückmeldung"``.
        days_remaining:
            Number of days until the deadline expires.
        language:
            ISO 639-1 language code.
        """
        admin_url = f"{self._settings.app_base_url}/admin/cases"
        context = {
            "case_number": case_number,
            "deadline_type": deadline_type,
            "days_remaining": str(days_remaining),
            "admin_url": admin_url,
        }
        await self._send_safe(
            to=to,
            template="deadline_warning",
            context=context,
            language=language,
        )

    # ── Magic link notification ──────────────────────────────────

    async def send_magic_link(
        self,
        *,
        to: str,
        magic_link_url: str,
        expire_minutes: int | None = None,
        language: str = "de",
    ) -> None:
        """Send a magic link for passwordless reporter authentication.

        Parameters
        ----------
        to:
            Reporter's email address.
        magic_link_url:
            Full URL with embedded JWT token for one-click login.
        expire_minutes:
            Link validity in minutes.  Defaults to the configured
            ``jwt_magic_link_expire_minutes`` setting.
        language:
            ISO 639-1 language code.
        """
        if expire_minutes is None:
            expire_minutes = self._settings.jwt_magic_link_expire_minutes

        context = {
            "magic_link_url": magic_link_url,
            "expire_minutes": str(expire_minutes),
        }
        await self._send_safe(
            to=to,
            template="magic_link",
            context=context,
            language=language,
        )

    # ── Private helpers ──────────────────────────────────────────

    async def _send_safe(
        self,
        *,
        to: str,
        template: str,
        context: dict[str, Any],
        language: str,
    ) -> None:
        """Send a templated email, catching and logging all errors.

        This wrapper ensures that SMTP failures are **never** propagated
        to the caller.  Notification delivery is best-effort: failures
        are logged as errors but do not break business logic.

        Parameters
        ----------
        to:
            Recipient email address.
        template:
            Template name (key in the SMTP module's template registry).
        context:
            Template placeholder values.
        language:
            ISO 639-1 language code.
        """
        try:
            await send_templated_email(
                to=to,
                template=template,
                context=context,
                language=language,
                tenant_smtp_config=self._tenant_smtp,
            )
            logger.info(
                "notification_sent",
                to=to,
                template=template,
                language=language,
            )
        except Exception:
            logger.error(
                "notification_send_failed",
                to=to,
                template=template,
                language=language,
                exc_info=True,
            )
