"""Hinweisgebersystem – Async SMTP Service.

Provides an asynchronous email sending service built on ``aiosmtplib``
with the following features:

- **STARTTLS / TLS support**: ``use_tls=True`` for port 465 (implicit
  TLS), STARTTLS upgrade for port 587 (default).
- **Per-tenant SMTP configuration**: tenants may override the global
  SMTP settings via their ``config`` JSONB column.
- **Email template rendering**: simple HTML templates per notification
  type, with language support (DE / EN).
- **Exponential backoff with 3 retries**: on transient SMTP failures
  the send is retried with delays of 2 s, 4 s, 8 s.
- **PGP email encryption**: if the recipient has a PGP public key on
  file, the email body is encrypted before sending.  Expired keys
  trigger a warning and fall back to unencrypted delivery.
- **Safety**: email bodies never contain sensitive case content — only
  links to the portal.

Usage::

    from app.core.smtp import send_email, send_templated_email

    # Send a plain email:
    await send_email(
        to="reporter@example.com",
        subject="Your report has been received",
        html_body="<p>Thank you for your report.</p>",
    )

    # Send a PGP-encrypted email:
    await send_email(
        to="handler@example.com",
        subject="New case assigned",
        html_body="<p>You have been assigned a new case.</p>",
        pgp_fingerprint="ABCDEF1234567890ABCDEF1234567890ABCDEF12",
    )

    # Send a templated notification (per-tenant config, language-aware):
    await send_templated_email(
        to="reporter@example.com",
        template="report_confirmation",
        context={"case_number": "HW-ABC12345", "portal_url": "https://..."},
        language="de",
        tenant_smtp_config=tenant.config.get("smtp"),
    )
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

import aiosmtplib
import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Maximum number of send attempts (1 initial + 2 retries = 3 total).
_MAX_RETRIES = 3

# Base delay in seconds for exponential backoff (2^attempt * base).
_BACKOFF_BASE_SECONDS = 2.0


# ── SMTP connection configuration ────────────────────────────


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """Immutable SMTP connection parameters.

    Constructed from either the global application settings or from a
    tenant-specific SMTP override stored in the ``tenants.config`` JSONB.
    """

    host: str
    port: int
    username: str
    password: str
    from_address: str
    use_tls: bool = False
    start_tls: bool = True

    @classmethod
    def from_settings(cls, settings: Any) -> SmtpConfig:
        """Create an ``SmtpConfig`` from global application settings.

        Parameters
        ----------
        settings:
            The application :class:`~app.core.config.Settings` instance.

        Returns
        -------
        SmtpConfig
            Configured with the global SMTP env vars.
        """
        # Port 465 → implicit TLS (use_tls=True, no STARTTLS upgrade).
        # Port 587 (default) → STARTTLS upgrade.
        use_tls = settings.smtp_port == 465
        start_tls = not use_tls

        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            from_address=settings.smtp_from,
            use_tls=use_tls,
            start_tls=start_tls,
        )

    @classmethod
    def from_tenant_config(
        cls,
        tenant_smtp: dict[str, Any],
        *,
        fallback: SmtpConfig,
    ) -> SmtpConfig:
        """Create an ``SmtpConfig`` from a tenant's SMTP override.

        Missing keys fall back to the values in *fallback* (the global
        configuration).

        Parameters
        ----------
        tenant_smtp:
            Dict from ``tenants.config["smtp"]``, e.g.::

                {
                    "host": "smtp.tenant.example.com",
                    "port": 587,
                    "username": "tenant-noreply",
                    "password": "s3cret",
                    "from_address": "noreply@tenant.example.com"
                }
        fallback:
            Global SMTP config used for any missing keys.

        Returns
        -------
        SmtpConfig
            Merged configuration.
        """
        port = int(tenant_smtp.get("port", fallback.port))
        use_tls = port == 465
        start_tls = not use_tls

        return cls(
            host=tenant_smtp.get("host", fallback.host),
            port=port,
            username=tenant_smtp.get("username", fallback.username),
            password=tenant_smtp.get("password", fallback.password),
            from_address=tenant_smtp.get("from_address", fallback.from_address),
            use_tls=use_tls,
            start_tls=start_tls,
        )


# ── Global config singleton ──────────────────────────────────

_global_config: SmtpConfig | None = None


def init_smtp(settings: Any | None = None) -> SmtpConfig:
    """Initialise the global SMTP configuration from application settings.

    Called once during application startup (lifespan).

    Parameters
    ----------
    settings:
        Application settings.  If ``None``, loaded via
        :func:`app.core.config.get_settings`.

    Returns
    -------
    SmtpConfig
        The global SMTP configuration.
    """
    global _global_config  # noqa: PLW0603

    if settings is None:
        from app.core.config import get_settings  # noqa: PLC0415

        settings = get_settings()

    _global_config = SmtpConfig.from_settings(settings)
    logger.info(
        "smtp_client_initialised",
        host=_global_config.host,
        port=_global_config.port,
        from_address=_global_config.from_address,
        use_tls=_global_config.use_tls,
        start_tls=_global_config.start_tls,
    )
    return _global_config


def get_smtp_config() -> SmtpConfig:
    """Return the global SMTP configuration singleton.

    Raises
    ------
    RuntimeError
        If :func:`init_smtp` has not been called yet.
    """
    if _global_config is None:
        raise RuntimeError(
            "SMTP not initialised. Call init_smtp() first."
        )
    return _global_config


# ── Core send function with retry ────────────────────────────


async def _send_raw(
    config: SmtpConfig,
    message: MIMEMultipart,
) -> None:
    """Send an email message via SMTP with exponential backoff.

    Retries up to :data:`_MAX_RETRIES` times on transient failures
    (connection errors, timeouts, temporary SMTP response codes).

    Parameters
    ----------
    config:
        SMTP connection parameters.
    message:
        Fully constructed email message.

    Raises
    ------
    aiosmtplib.SMTPException
        If all retry attempts are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            await aiosmtplib.send(
                message,
                hostname=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                use_tls=config.use_tls,
                start_tls=config.start_tls,
            )
            logger.info(
                "smtp_email_sent",
                to=message["To"],
                subject=message["Subject"],
                attempt=attempt,
            )
            return

        except (
            aiosmtplib.SMTPConnectError,
            aiosmtplib.SMTPConnectTimeoutError,
            aiosmtplib.SMTPServerDisconnected,
            aiosmtplib.SMTPResponseException,
            OSError,
        ) as exc:
            last_exception = exc
            if attempt < _MAX_RETRIES:
                delay = _BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    "smtp_send_retry",
                    to=message["To"],
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    delay_seconds=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "smtp_send_failed",
                    to=message["To"],
                    subject=message["Subject"],
                    attempts=_MAX_RETRIES,
                    error=str(exc),
                )

    if last_exception is not None:
        raise last_exception


def _build_message(
    *,
    to: str,
    subject: str,
    html_body: str,
    from_address: str,
    text_body: str | None = None,
) -> MIMEMultipart:
    """Build a MIME multipart email message.

    Parameters
    ----------
    to:
        Recipient email address.
    subject:
        Email subject line.
    html_body:
        HTML content of the email.
    from_address:
        Sender address.
    text_body:
        Optional plain-text fallback.  If ``None``, a minimal fallback
        is auto-generated from the subject.

    Returns
    -------
    MIMEMultipart
        Ready-to-send email message.
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject

    # Plain-text fallback for clients that don't render HTML.
    if text_body is None:
        text_body = (
            f"{subject}\n\n"
            "Please view this email in an HTML-capable client."
        )
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


def _build_pgp_message(
    *,
    to: str,
    subject: str,
    encrypted_body: str,
    from_address: str,
) -> MIMEMultipart:
    """Build a MIME message with a PGP-encrypted body.

    When PGP encryption is active, the email contains a single
    ``text/plain`` part with the ASCII-armored PGP ciphertext.
    The recipient's email client (or PGP plugin) decrypts the
    content to reveal the original HTML body.

    Parameters
    ----------
    to:
        Recipient email address.
    subject:
        Email subject line (always sent in cleartext).
    encrypted_body:
        ASCII-armored PGP-encrypted content.
    from_address:
        Sender address.

    Returns
    -------
    MIMEMultipart
        Ready-to-send email message with encrypted body.
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject

    # The encrypted body replaces both plain-text and HTML parts.
    # PGP-aware clients will decrypt; others see the PGP block.
    msg.attach(MIMEText(encrypted_body, "plain", "utf-8"))

    return msg


def _maybe_pgp_encrypt(
    *,
    html_body: str,
    pgp_fingerprint: str | None,
) -> str | None:
    """Attempt PGP encryption of the email body if a fingerprint is provided.

    This function implements a **fail-open** policy: if encryption
    cannot be performed (expired key, missing key, service error),
    the email is sent unencrypted and a warning is logged.  This
    ensures notification delivery is never blocked by PGP issues.

    Parameters
    ----------
    html_body:
        The HTML body to encrypt.
    pgp_fingerprint:
        The recipient's 40-character PGP key fingerprint.  If
        ``None``, no encryption is attempted and ``None`` is returned.

    Returns
    -------
    str | None
        The ASCII-armored PGP-encrypted body, or ``None`` if
        encryption was skipped or failed (fall-back to unencrypted).
    """
    if not pgp_fingerprint:
        return None

    try:
        from app.services.pgp_service import (  # noqa: PLC0415
            PGPEncryptionError,
            PGPKeyExpiredError,
            get_pgp_service,
        )

        pgp = get_pgp_service()

        # Check expiry before attempting encryption.
        if pgp.is_key_expired(pgp_fingerprint):
            logger.warning(
                "pgp_key_expired_fallback_unencrypted",
                fingerprint=pgp_fingerprint,
                reason="PGP key has expired; sending email unencrypted.",
            )
            return None

        encrypted = pgp.encrypt_message(html_body, pgp_fingerprint)

        logger.info(
            "pgp_email_body_encrypted",
            fingerprint=pgp_fingerprint,
        )

        return encrypted

    except PGPKeyExpiredError:
        logger.warning(
            "pgp_key_expired_fallback_unencrypted",
            fingerprint=pgp_fingerprint,
            reason="PGP key expired during encryption; sending unencrypted.",
        )
        return None

    except PGPEncryptionError:
        logger.warning(
            "pgp_encryption_failed_fallback_unencrypted",
            fingerprint=pgp_fingerprint,
            reason="PGP encryption failed; sending email unencrypted.",
            exc_info=True,
        )
        return None

    except Exception:
        # Catch-all for unexpected PGP errors (e.g. keyring issues).
        # Notifications must never fail because of PGP problems.
        logger.warning(
            "pgp_unexpected_error_fallback_unencrypted",
            fingerprint=pgp_fingerprint,
            reason="Unexpected PGP error; sending email unencrypted.",
            exc_info=True,
        )
        return None


# ── Public send API ──────────────────────────────────────────


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    tenant_smtp_config: dict[str, Any] | None = None,
    pgp_fingerprint: str | None = None,
) -> None:
    """Send an email using the global or tenant-specific SMTP config.

    If *pgp_fingerprint* is provided, the email body is encrypted
    with the recipient's PGP public key before sending.  When the
    key is expired or encryption fails, the email is sent unencrypted
    and a warning is logged (fail-open policy).

    Parameters
    ----------
    to:
        Recipient email address.
    subject:
        Email subject line.
    html_body:
        HTML body content.
    text_body:
        Optional plain-text body fallback.
    tenant_smtp_config:
        Optional per-tenant SMTP override dict (from
        ``tenants.config["smtp"]``).  If ``None``, uses the global
        SMTP configuration.
    pgp_fingerprint:
        Optional PGP key fingerprint for the recipient.  If provided,
        the email body is PGP-encrypted.  If the key is expired or
        encryption fails, delivery falls back to unencrypted.

    Raises
    ------
    RuntimeError
        If SMTP is not initialised.
    aiosmtplib.SMTPException
        If sending fails after all retries.
    """
    global_cfg = get_smtp_config()

    if tenant_smtp_config:
        config = SmtpConfig.from_tenant_config(
            tenant_smtp_config,
            fallback=global_cfg,
        )
    else:
        config = global_cfg

    # Attempt PGP encryption if the recipient has a key on file.
    encrypted_body = _maybe_pgp_encrypt(
        html_body=html_body,
        pgp_fingerprint=pgp_fingerprint,
    )

    if encrypted_body is not None:
        # PGP encryption succeeded — send the encrypted message.
        message = _build_pgp_message(
            to=to,
            subject=subject,
            encrypted_body=encrypted_body,
            from_address=config.from_address,
        )
    else:
        # No PGP key, or encryption failed — send unencrypted.
        message = _build_message(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_address=config.from_address,
        )

    await _send_raw(config, message)


# ── Email templates ──────────────────────────────────────────
# Templates are minimal HTML strings.  Email bodies NEVER contain
# sensitive case content — only links to the portal.


_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "report_confirmation": {
        "de": {
            "subject": "Ihre Meldung wurde eingereicht – Fallnummer {case_number}",
            "html": (
                "<html><body>"
                "<h2>Vielen Dank für Ihre Meldung</h2>"
                "<p>Ihre Meldung wurde erfolgreich eingereicht.</p>"
                "<p><strong>Fallnummer:</strong> {case_number}</p>"
                "<p>Sie können den Status Ihrer Meldung über Ihr sicheres Postfach "
                "einsehen:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "<p>Bitte bewahren Sie Ihre Zugangsdaten sicher auf.</p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "Your report has been submitted – Case {case_number}",
            "html": (
                "<html><body>"
                "<h2>Thank you for your report</h2>"
                "<p>Your report has been submitted successfully.</p>"
                "<p><strong>Case number:</strong> {case_number}</p>"
                "<p>You can view the status of your report via your secure "
                "mailbox:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "<p>Please keep your access credentials safe.</p>"
                "</body></html>"
            ),
        },
    },
    "new_message": {
        "de": {
            "subject": "Neue Nachricht zu Ihrer Meldung – {case_number}",
            "html": (
                "<html><body>"
                "<h2>Neue Nachricht</h2>"
                "<p>Zu Ihrer Meldung <strong>{case_number}</strong> liegt eine "
                "neue Nachricht vor.</p>"
                "<p>Bitte melden Sie sich in Ihrem sicheren Postfach an, um die "
                "Nachricht zu lesen:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "New message regarding your report – {case_number}",
            "html": (
                "<html><body>"
                "<h2>New Message</h2>"
                "<p>There is a new message regarding your report "
                "<strong>{case_number}</strong>.</p>"
                "<p>Please log in to your secure mailbox to read it:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "</body></html>"
            ),
        },
    },
    "status_change": {
        "de": {
            "subject": "Statusänderung Ihrer Meldung – {case_number}",
            "html": (
                "<html><body>"
                "<h2>Statusänderung</h2>"
                "<p>Der Status Ihrer Meldung <strong>{case_number}</strong> "
                "wurde aktualisiert.</p>"
                "<p>Bitte melden Sie sich in Ihrem sicheren Postfach an, um "
                "Details einzusehen:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "Status update for your report – {case_number}",
            "html": (
                "<html><body>"
                "<h2>Status Update</h2>"
                "<p>The status of your report <strong>{case_number}</strong> "
                "has been updated.</p>"
                "<p>Please log in to your secure mailbox for details:</p>"
                "<p><a href=\"{portal_url}\">{portal_url}</a></p>"
                "</body></html>"
            ),
        },
    },
    "magic_link": {
        "de": {
            "subject": "Ihr Anmeldelink – Hinweisgebersystem",
            "html": (
                "<html><body>"
                "<h2>Anmeldelink</h2>"
                "<p>Klicken Sie auf den folgenden Link, um sich anzumelden:</p>"
                "<p><a href=\"{magic_link_url}\">{magic_link_url}</a></p>"
                "<p>Dieser Link ist {expire_minutes} Minuten gültig.</p>"
                "<p>Falls Sie diesen Link nicht angefordert haben, können Sie "
                "diese E-Mail ignorieren.</p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "Your login link – Whistleblower Portal",
            "html": (
                "<html><body>"
                "<h2>Login Link</h2>"
                "<p>Click the link below to log in:</p>"
                "<p><a href=\"{magic_link_url}\">{magic_link_url}</a></p>"
                "<p>This link is valid for {expire_minutes} minutes.</p>"
                "<p>If you did not request this link, you can safely ignore "
                "this email.</p>"
                "</body></html>"
            ),
        },
    },
    "case_assignment": {
        "de": {
            "subject": "Neuer Fall zugewiesen – {case_number}",
            "html": (
                "<html><body>"
                "<h2>Fallzuweisung</h2>"
                "<p>Ihnen wurde der Fall <strong>{case_number}</strong> "
                "zugewiesen.</p>"
                "<p>Bitte melden Sie sich im Admin-Portal an:</p>"
                "<p><a href=\"{admin_url}\">{admin_url}</a></p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "New case assigned – {case_number}",
            "html": (
                "<html><body>"
                "<h2>Case Assignment</h2>"
                "<p>You have been assigned case "
                "<strong>{case_number}</strong>.</p>"
                "<p>Please log in to the admin portal:</p>"
                "<p><a href=\"{admin_url}\">{admin_url}</a></p>"
                "</body></html>"
            ),
        },
    },
    "deadline_warning": {
        "de": {
            "subject": "Fristwarnung – {case_number} ({deadline_type})",
            "html": (
                "<html><body>"
                "<h2>Fristwarnung</h2>"
                "<p>Die Frist <strong>{deadline_type}</strong> für den Fall "
                "<strong>{case_number}</strong> läuft in "
                "<strong>{days_remaining} Tagen</strong> ab.</p>"
                "<p>Bitte überprüfen Sie den Fall im Admin-Portal:</p>"
                "<p><a href=\"{admin_url}\">{admin_url}</a></p>"
                "</body></html>"
            ),
        },
        "en": {
            "subject": "Deadline warning – {case_number} ({deadline_type})",
            "html": (
                "<html><body>"
                "<h2>Deadline Warning</h2>"
                "<p>The <strong>{deadline_type}</strong> deadline for case "
                "<strong>{case_number}</strong> expires in "
                "<strong>{days_remaining} days</strong>.</p>"
                "<p>Please review the case in the admin portal:</p>"
                "<p><a href=\"{admin_url}\">{admin_url}</a></p>"
                "</body></html>"
            ),
        },
    },
}


def render_template(
    template: str,
    context: dict[str, Any],
    *,
    language: str = "de",
) -> tuple[str, str]:
    """Render an email template with the given context variables.

    Parameters
    ----------
    template:
        Template name (key in :data:`_TEMPLATES`), e.g.
        ``"report_confirmation"``, ``"new_message"``.
    context:
        Dict of placeholder values, e.g.
        ``{"case_number": "HW-XYZ", "portal_url": "https://..."}``.
    language:
        ISO 639-1 language code (``"de"`` or ``"en"``).  Defaults to
        ``"de"`` (German).

    Returns
    -------
    tuple[str, str]
        ``(subject, html_body)`` with placeholders replaced.

    Raises
    ------
    ValueError
        If the template name or language is not found.
    """
    if template not in _TEMPLATES:
        raise ValueError(
            f"Unknown email template: {template!r}. "
            f"Available: {sorted(_TEMPLATES.keys())}"
        )

    lang_templates = _TEMPLATES[template]
    if language not in lang_templates:
        # Fall back to German if the requested language is not available.
        language = "de"
        if language not in lang_templates:
            raise ValueError(
                f"Template {template!r} has no translation for "
                f"language {language!r}."
            )

    tpl = lang_templates[language]
    subject = tpl["subject"].format_map(context)
    html_body = tpl["html"].format_map(context)

    return subject, html_body


async def send_templated_email(
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    language: str = "de",
    tenant_smtp_config: dict[str, Any] | None = None,
    pgp_fingerprint: str | None = None,
) -> None:
    """Render a template and send the resulting email.

    This is the primary high-level function used by notification
    services.  It combines template rendering with the retry-enabled
    send pipeline.

    If *pgp_fingerprint* is provided, the rendered email body is
    PGP-encrypted before sending.

    Parameters
    ----------
    to:
        Recipient email address.
    template:
        Template name (e.g. ``"report_confirmation"``).
    context:
        Template placeholder values.
    language:
        Language code (``"de"`` or ``"en"``).
    tenant_smtp_config:
        Optional per-tenant SMTP override dict.
    pgp_fingerprint:
        Optional PGP key fingerprint for the recipient.  Passed
        through to :func:`send_email` for encryption.

    Raises
    ------
    ValueError
        If the template or language is invalid.
    RuntimeError
        If SMTP is not initialised.
    aiosmtplib.SMTPException
        If sending fails after all retries.
    """
    subject, html_body = render_template(template, context, language=language)

    await send_email(
        to=to,
        subject=subject,
        html_body=html_body,
        tenant_smtp_config=tenant_smtp_config,
        pgp_fingerprint=pgp_fingerprint,
    )
