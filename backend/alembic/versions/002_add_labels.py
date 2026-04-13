"""Add labels table and report_labels junction table with RLS policies.

Creates the labeling/tagging system for reports:
- Creates labels table (tenant-scoped, color-coded tags)
- Creates report_labels junction table (many-to-many)
- Enables Row-Level Security on both tables
- Creates tenant_isolation policies
- Adds updated_at trigger for labels table
- Grants permissions to app_user role

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that need RLS policies in this migration.
_LABEL_RLS_TABLES = ["labels", "report_labels"]


def upgrade() -> None:
    """Apply schema changes."""

    # ── 1. Labels table ──────────────────────────────────────
    op.create_table(
        "labels",
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
            "name",
            sa.String(100),
            nullable=False,
            comment="Human-readable label name",
        ),
        sa.Column(
            "color",
            sa.String(7),
            nullable=False,
            server_default=sa.text("'#6B7280'"),
            comment="Hex colour code for UI display (e.g. #FF5733)",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment="Optional description of the label's purpose",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Inactive labels are hidden from new assignments",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_labels_tenant_name",
        ),
    )
    op.create_index("ix_labels_tenant_id", "labels", ["tenant_id"])

    # ── 2. Report-labels junction table ──────────────────────
    op.create_table(
        "report_labels",
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("labels.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Timestamp when the label was assigned to the report",
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="User who assigned the label (NULL for system actions)",
        ),
    )
    op.create_index(
        "ix_report_labels_label_id", "report_labels", ["label_id"]
    )

    # ── 3. Row-Level Security ────────────────────────────────

    # 3a. Labels — direct tenant_id column
    op.execute("ALTER TABLE labels ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY labels_tenant_isolation ON labels
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    op.execute("ALTER TABLE labels FORCE ROW LEVEL SECURITY")

    # 3b. Report-labels — no tenant_id; use subquery against labels
    op.execute("ALTER TABLE report_labels ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY report_labels_tenant_isolation ON report_labels
            USING (label_id IN (
                SELECT id FROM labels
                WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
            ))
            WITH CHECK (label_id IN (
                SELECT id FROM labels
                WHERE tenant_id = current_setting('app.current_tenant_id')::uuid
            ))
    """)
    op.execute("ALTER TABLE report_labels FORCE ROW LEVEL SECURITY")

    # ── 4. Grant permissions to app_user ─────────────────────
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON labels TO app_user"
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON report_labels TO app_user"
    )

    # ── 5. updated_at auto-update trigger for labels ─────────
    # Reuses the update_updated_at_column() function created in 0001.
    op.execute("""
        CREATE TRIGGER trg_labels_updated_at
            BEFORE UPDATE ON labels
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """Revert schema changes."""

    # ── Remove updated_at trigger ────────────────────────────
    op.execute("DROP TRIGGER IF EXISTS trg_labels_updated_at ON labels")

    # ── Revoke permissions from app_user ─────────────────────
    op.execute(
        "REVOKE SELECT, INSERT, DELETE ON report_labels FROM app_user"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON labels FROM app_user"
    )

    # ── Remove RLS policies ──────────────────────────────────
    op.execute(
        "ALTER TABLE report_labels NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS report_labels_tenant_isolation ON report_labels"
    )
    op.execute("ALTER TABLE report_labels DISABLE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE labels NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS labels_tenant_isolation ON labels"
    )
    op.execute("ALTER TABLE labels DISABLE ROW LEVEL SECURITY")

    # ── Drop tables (reverse dependency order) ───────────────
    op.drop_table("report_labels")
    op.drop_table("labels")
