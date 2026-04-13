"""Add sub_statuses table and sub_status_id FK on reports with RLS policy.

Creates the configurable sub-statuses system for case management:
- Creates sub_statuses table (tenant-scoped, per-parent-status refinements)
- Adds sub_status_id FK column on reports (nullable, SET NULL on delete)
- Enables Row-Level Security on sub_statuses table
- Creates tenant_isolation policy
- Grants permissions to app_user role

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply schema changes."""

    # ── 1. Sub-statuses table ───────────────────────────────────
    op.create_table(
        "sub_statuses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_status",
            sa.String(50),
            nullable=False,
            comment="Maps to ReportStatus enum value",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="Human-readable sub-status label",
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Sort order within parent status group (ascending)",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Auto-assign when report transitions to parent status",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Inactive sub-statuses are hidden from new assignments",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "parent_status",
            "name",
            name="uq_substatus_tenant_parent_name",
        ),
    )
    op.create_index(
        "ix_sub_statuses_tenant_id", "sub_statuses", ["tenant_id"]
    )
    op.create_index(
        "ix_sub_statuses_parent_status", "sub_statuses", ["parent_status"]
    )

    # ── 2. Add sub_status_id FK on reports ──────────────────────
    op.add_column(
        "reports",
        sa.Column(
            "sub_status_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sub_statuses.id", ondelete="SET NULL"),
            nullable=True,
            comment="Optional configurable sub-status within the current status",
        ),
    )
    op.create_index(
        "ix_reports_sub_status_id", "reports", ["sub_status_id"]
    )

    # ── 3. Row-Level Security ───────────────────────────────────
    op.execute("ALTER TABLE sub_statuses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY sub_statuses_tenant_isolation ON sub_statuses
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    op.execute("ALTER TABLE sub_statuses FORCE ROW LEVEL SECURITY")

    # ── 4. Grant permissions to app_user ────────────────────────
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON sub_statuses TO app_user"
    )


def downgrade() -> None:
    """Revert schema changes."""

    # ── Revoke permissions from app_user ────────────────────────
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON sub_statuses FROM app_user"
    )

    # ── Remove RLS policies ─────────────────────────────────────
    op.execute("ALTER TABLE sub_statuses NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS sub_statuses_tenant_isolation ON sub_statuses"
    )
    op.execute("ALTER TABLE sub_statuses DISABLE ROW LEVEL SECURITY")

    # ── Remove sub_status_id from reports ───────────────────────
    op.drop_index("ix_reports_sub_status_id", table_name="reports")
    op.drop_column("reports", "sub_status_id")

    # ── Drop sub_statuses table ─────────────────────────────────
    op.drop_table("sub_statuses")
