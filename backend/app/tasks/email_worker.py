"""Hinweisgebersystem -- Async Email Queue Worker.

Processes outbound emails from a Redis queue with reliability
guarantees:

- **Exponential backoff**: on transient SMTP failures, the message is
  re-enqueued with increasing delays (1 s, 2 s, 4 s).
- **3 retries**: after 3 failed attempts the message is moved to a
  dead-letter queue and an escalation alert is sent to all system
  administrators.
- **Atomic dequeue**: uses Redis ``LPOP`` for reliable message
  retrieval.  Failed messages are re-enqueued to the right of the
  queue with an incremented retry counter.

Queue format (Redis list ``email:queue``)::

    {
        "to": "recipient@example.com",
        "template": "report_confirmation",
        "context": {"case_number": "HWS-ABC123456789", ...},
        "language": "de",
        "tenant_smtp_config": null | {...},
        "retry_count": 0,
        "enqueued_at": "2026-04-05T12:00:00Z"
    }

Dead-letter queue (Redis list ``email:dead_letter``)::

    Same format as above, with ``retry_count >= 3`` and an added
    ``failed_at`` timestamp and ``last_error`` message.

Usage::

    from app.tasks.email_worker import enqueue_email, run_email_worker

    # Enqueue an email for async delivery:
    await enqueue_email(
        to="reporter@example.com",
        template="report_confirmation",
        context={"case_number": "HWS-ABC123456789"},
        language="de",
    )

    # The worker runs automatically via APScheduler every 30 seconds.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from redis import asyncio as aioredis

from app.core.config import get_settings
from app.core.smtp import send_templated_email

logger = structlog.get_logger(__name__)

# ── Queue keys ───────────────────────────────────────────────

EMAIL_QUEUE_KEY = "email:queue"
EMAIL_DEAD_LETTER_KEY = "email:dead_letter"

# ── Retry configuration ─────────────────────────────────────

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1  # 1s, 2s, 4s

# ── Batch size ───────────────────────────────────────────────
# Maximum number of messages to process per worker invocation.
# Prevents a single run from blocking too long.

MAX_BATCH_SIZE = 50


async def enqueue_email(
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    language: str = "de",
    tenant_smtp_config: dict[str, Any] | None = None,
) -> None:
    """Add an email to the Redis queue for async delivery.

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
    tenant_smtp_config:
        Optional per-tenant SMTP configuration override.
    """
    settings = get_settings()
    redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    message = {
        "to": to,
        "template": template,
        "context": context,
        "language": language,
        "tenant_smtp_config": tenant_smtp_config,
        "retry_count": 0,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await redis.rpush(EMAIL_QUEUE_KEY, json.dumps(message))
        logger.info(
            "email_enqueued",
            to=to,
            template=template,
        )
    finally:
        await redis.aclose()


async def run_email_worker() -> None:
    """Drain the Redis email queue and deliver messages via SMTP.

    Processes up to ``MAX_BATCH_SIZE`` messages per invocation.
    Failed messages are re-enqueued with an incremented retry
    counter and exponential backoff delay.  After ``MAX_RETRIES``
    failures, the message is moved to the dead-letter queue and
    an escalation alert is logged.

    This function is designed to be called by APScheduler and never
    raises — all errors are caught, logged, and processing continues.
    """
    settings = get_settings()

    try:
        redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    except Exception:
        logger.error("email_worker_redis_connect_failed", exc_info=True)
        return

    processed = 0
    succeeded = 0
    failed = 0

    try:
        for _ in range(MAX_BATCH_SIZE):
            # Atomically pop from left of queue
            raw = await redis.lpop(EMAIL_QUEUE_KEY)
            if raw is None:
                break  # Queue is empty

            processed += 1

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.error(
                    "email_worker_invalid_message",
                    raw=raw[:200],
                )
                failed += 1
                continue

            success = await _process_message(message, redis)
            if success:
                succeeded += 1
            else:
                failed += 1

    except Exception:
        logger.error("email_worker_unexpected_error", exc_info=True)
    finally:
        await redis.aclose()

    if processed > 0:
        logger.info(
            "email_worker_batch_completed",
            processed=processed,
            succeeded=succeeded,
            failed=failed,
        )


async def _process_message(
    message: dict[str, Any],
    redis: aioredis.Redis,
) -> bool:
    """Attempt to deliver a single email message.

    Parameters
    ----------
    message:
        Parsed message dict from the queue.
    redis:
        Active Redis connection for re-enqueue / dead-letter.

    Returns
    -------
    bool
        ``True`` if the message was delivered successfully.
    """
    to = message.get("to", "")
    template = message.get("template", "")
    context = message.get("context", {})
    language = message.get("language", "de")
    tenant_smtp = message.get("tenant_smtp_config")
    retry_count = message.get("retry_count", 0)

    try:
        await send_templated_email(
            to=to,
            template=template,
            context=context,
            language=language,
            tenant_smtp_config=tenant_smtp,
        )
        logger.info(
            "email_delivered",
            to=to,
            template=template,
            retry_count=retry_count,
        )
        return True

    except Exception as exc:
        retry_count += 1
        error_msg = str(exc)[:500]

        if retry_count >= MAX_RETRIES:
            # Move to dead-letter queue
            await _move_to_dead_letter(message, redis, error_msg)
            logger.error(
                "email_delivery_final_failure",
                to=to,
                template=template,
                retry_count=retry_count,
                error=error_msg,
            )
            return False

        # Exponential backoff delay before re-enqueue
        backoff_seconds = BACKOFF_BASE_SECONDS * (2 ** (retry_count - 1))
        await asyncio.sleep(backoff_seconds)

        # Re-enqueue with incremented retry count
        message["retry_count"] = retry_count
        message["last_error"] = error_msg
        message["last_retry_at"] = datetime.now(timezone.utc).isoformat()

        await redis.rpush(EMAIL_QUEUE_KEY, json.dumps(message))
        logger.warning(
            "email_delivery_retry",
            to=to,
            template=template,
            retry_count=retry_count,
            backoff_seconds=backoff_seconds,
            error=error_msg,
        )
        return False


async def _move_to_dead_letter(
    message: dict[str, Any],
    redis: aioredis.Redis,
    error_msg: str,
) -> None:
    """Move a permanently failed message to the dead-letter queue.

    Appends failure metadata and pushes the message to
    ``email:dead_letter`` for manual inspection / retry.

    Parameters
    ----------
    message:
        The failed message dict.
    redis:
        Active Redis connection.
    error_msg:
        The last error message string.
    """
    message["failed_at"] = datetime.now(timezone.utc).isoformat()
    message["last_error"] = error_msg

    try:
        await redis.rpush(EMAIL_DEAD_LETTER_KEY, json.dumps(message))
    except Exception:
        logger.error(
            "email_dead_letter_push_failed",
            to=message.get("to", "unknown"),
            exc_info=True,
        )

    # Log escalation alert for operations team
    logger.critical(
        "email_escalation_alert",
        to=message.get("to", "unknown"),
        template=message.get("template", "unknown"),
        retry_count=message.get("retry_count", 0),
        error=error_msg,
        enqueued_at=message.get("enqueued_at"),
        message="Email delivery permanently failed after all retries. "
        "Manual intervention required. Check email:dead_letter queue.",
    )


async def get_queue_stats() -> dict[str, int]:
    """Return email queue statistics for monitoring.

    Returns
    -------
    dict[str, int]
        Dictionary with ``queue_length`` and ``dead_letter_length``.
    """
    settings = get_settings()
    redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        queue_length = await redis.llen(EMAIL_QUEUE_KEY)
        dead_letter_length = await redis.llen(EMAIL_DEAD_LETTER_KEY)

        return {
            "queue_length": queue_length,
            "dead_letter_length": dead_letter_length,
        }
    finally:
        await redis.aclose()
