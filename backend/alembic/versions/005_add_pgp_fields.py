"""Add PGP email encryption fields to users table.

Adds three columns for PGP-encrypted email notification support:
- pgp_public_key (TEXT): ASCII-armored PGP public key
- pgp_fingerprint (VARCHAR(64)): PGP key fingerprint for lookup
- pgp_key_expires_at (TIMESTAMPTZ): when the PGP key expires

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply schema changes."""

    # ── 1. Add pgp_public_key (TEXT — ASCII-armored PGP key) ───────
    op.add_column(
        "users",
        sa.Column(
            "pgp_public_key",
            sa.Text(),
            nullable=True,
            comment="ASCII-armored PGP public key for encrypted email notifications",
        ),
    )

    # ── 2. Add pgp_fingerprint (VARCHAR(64)) ───────────────────────
    op.add_column(
        "users",
        sa.Column(
            "pgp_fingerprint",
            sa.String(64),
            nullable=True,
            comment="PGP key fingerprint for key identification",
        ),
    )

    # ── 3. Add pgp_key_expires_at (TIMESTAMPTZ) ───────────────────
    op.add_column(
        "users",
        sa.Column(
            "pgp_key_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="PGP key expiration date (NULL if key does not expire)",
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""

    op.drop_column("users", "pgp_key_expires_at")
    op.drop_column("users", "pgp_fingerprint")
    op.drop_column("users", "pgp_public_key")
