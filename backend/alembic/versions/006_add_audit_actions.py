"""Add new AuditAction enum values for labels, sub-statuses, TOTP, and PGP.

Extends the PostgreSQL audit_action enum type with 15 new values introduced
by the GlobaLeaks feature gap implementation:

Labels (5):
  label.created, label.updated, label.deleted, label.assigned, label.removed

Sub-statuses (3):
  sub_status.created, sub_status.updated, sub_status.deleted

TOTP Two-Factor Authentication (4):
  totp.enabled, totp.disabled, totp.reset, totp.challenge_failed

PGP Key Management (3):
  pgp.key_uploaded, pgp.key_deleted, pgp.key_expired

Uses ALTER TYPE ... ADD VALUE IF NOT EXISTS for idempotency.  PostgreSQL 12+
supports ADD VALUE inside transactions; the new values are not referenced
within this migration, so there are no same-transaction visibility issues.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-08
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── New audit_action enum values ─────────────────────────────

_NEW_AUDIT_ACTIONS: list[str] = [
    # Label management
    "label.created",
    "label.updated",
    "label.deleted",
    "label.assigned",
    "label.removed",
    # Sub-status management
    "sub_status.created",
    "sub_status.updated",
    "sub_status.deleted",
    # TOTP Two-Factor Authentication
    "totp.enabled",
    "totp.disabled",
    "totp.reset",
    "totp.challenge_failed",
    # PGP Key Management
    "pgp.key_uploaded",
    "pgp.key_deleted",
    "pgp.key_expired",
]


def upgrade() -> None:
    """Add new enum values to the audit_action PostgreSQL enum type."""

    for value in _NEW_AUDIT_ACTIONS:
        op.execute(
            f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    """Remove new enum values from the audit_action PostgreSQL enum type.

    PostgreSQL does not support ``ALTER TYPE ... DROP VALUE``.  The only
    way to shrink an enum is to recreate the type.  Because the audit_logs
    table is append-only and may already contain rows with the new values,
    we recreate the type only if no rows reference the values being removed.

    Steps:
    1. Rename the current enum to a temporary name.
    2. Create a new enum with only the original values.
    3. Alter the audit_logs.action column to use the new enum.
    4. Drop the old (renamed) enum.

    If any audit_logs rows use a new value, the ALTER COLUMN … USING cast
    will fail, which is the correct behavior — data must not be silently
    discarded.
    """

    # Original audit_action values from migration 0001.
    _ORIGINAL_VALUES = (
        "'case.created',"
        "'case.status_changed',"
        "'case.assigned',"
        "'case.priority_changed',"
        "'case.deleted',"
        "'message.sent',"
        "'message.read',"
        "'attachment.uploaded',"
        "'attachment.downloaded',"
        "'identity.disclosure_requested',"
        "'identity.disclosure_approved',"
        "'identity.disclosure_rejected',"
        "'identity.disclosed',"
        "'user.created',"
        "'user.updated',"
        "'user.deactivated',"
        "'user.login',"
        "'user.logout',"
        "'tenant.created',"
        "'tenant.updated',"
        "'tenant.deactivated',"
        "'category.created',"
        "'category.updated',"
        "'category.deleted',"
        "'mailbox.login',"
        "'mailbox.login_failed',"
        "'magic_link.requested',"
        "'magic_link.used',"
        "'data_retention.executed',"
        "'system.error'"
    )

    # 1. Rename current enum
    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")

    # 2. Create new enum with only original values
    op.execute(
        f"CREATE TYPE audit_action AS ENUM ({_ORIGINAL_VALUES})"
    )

    # 3. Migrate the column — will fail if rows reference removed values
    op.execute(
        "ALTER TABLE audit_logs "
        "ALTER COLUMN action TYPE audit_action "
        "USING action::text::audit_action"
    )

    # 4. Drop the old enum
    op.execute("DROP TYPE audit_action_old")
