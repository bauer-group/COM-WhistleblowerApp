"""Add TOTP two-factor authentication fields to users table.

Adds five columns for TOTP 2FA support:
- totp_secret (BYTEA): encrypted shared secret via pgcrypto PGPString
- totp_enabled (BOOLEAN): whether 2FA is active for the user
- totp_verified_at (TIMESTAMPTZ): when TOTP setup was first verified
- totp_last_used_at (TIMESTAMPTZ): last successful TOTP verification
- totp_backup_codes_hash (TEXT[]): bcrypt hashes of recovery codes

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply schema changes."""

    # ── 1. Add totp_secret (BYTEA — pgcrypto encrypted) ─────────
    op.add_column(
        "users",
        sa.Column(
            "totp_secret",
            sa.LargeBinary(),
            nullable=True,
            comment="TOTP shared secret (pgcrypto encrypted)",
        ),
    )

    # ── 2. Add totp_enabled (BOOLEAN, default false) ────────────
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether TOTP 2FA is active",
        ),
    )

    # ── 3. Add totp_verified_at (TIMESTAMPTZ) ───────────────────
    op.add_column(
        "users",
        sa.Column(
            "totp_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When TOTP setup was first verified",
        ),
    )

    # ── 4. Add totp_last_used_at (TIMESTAMPTZ) ──────────────────
    op.add_column(
        "users",
        sa.Column(
            "totp_last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last successful TOTP verification",
        ),
    )

    # ── 5. Add totp_backup_codes_hash (TEXT[]) ───────────────────
    op.add_column(
        "users",
        sa.Column(
            "totp_backup_codes_hash",
            postgresql.ARRAY(sa.String()),
            nullable=True,
            comment="Hashed TOTP backup/recovery codes",
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""

    op.drop_column("users", "totp_backup_codes_hash")
    op.drop_column("users", "totp_last_used_at")
    op.drop_column("users", "totp_verified_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
