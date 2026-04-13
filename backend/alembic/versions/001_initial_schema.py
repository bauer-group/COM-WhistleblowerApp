"""Initial schema: pgcrypto, app_user role, all tables, RLS, audit immutability.

Creates the complete database schema for the Hinweisgebersystem:
- Enables pgcrypto extension for field-level encryption
- Creates non-superuser app_user role for RLS enforcement
- Creates all 8 tables (tenants, reports, messages, attachments, users,
  audit_logs, category_translations, identity_disclosures)
- Enables Row-Level Security on all tenant-scoped tables
- Creates tenant_isolation policies using current_setting('app.current_tenant_id')
- Creates tsvector GIN index for German full-text search on reports
- Blocks UPDATE/DELETE on audit_logs via trigger (append-only immutability)
- Grants permissions to app_user role

Revision ID: 0001
Revises: None
Create Date: 2026-04-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Enum definitions ─────────────────────────────────────────

# These match the Python enums in app/models/*.py exactly.

channel_type = postgresql.ENUM(
    "hinschg",
    "lksg",
    name="channel_type",
    create_type=False,
)
report_status = postgresql.ENUM(
    "eingegangen",
    "in_pruefung",
    "in_bearbeitung",
    "rueckmeldung",
    "abgeschlossen",
    name="report_status",
    create_type=False,
)
priority_level = postgresql.ENUM(
    "low",
    "medium",
    "high",
    "critical",
    name="priority_level",
    create_type=False,
)
supply_chain_tier = postgresql.ENUM(
    "own_operations",
    "direct_supplier",
    "indirect_supplier",
    "unknown",
    name="supply_chain_tier",
    create_type=False,
)
reporter_relationship = postgresql.ENUM(
    "employee",
    "supplier",
    "contractor",
    "community_member",
    "ngo",
    "other",
    name="reporter_relationship",
    create_type=False,
)
lksg_category = postgresql.ENUM(
    "child_labor",
    "forced_labor",
    "discrimination",
    "freedom_of_association",
    "working_conditions",
    "fair_wages",
    "environmental_damage",
    "land_rights",
    "security_forces",
    "other_human_rights",
    "other_environmental",
    name="lksg_category",
    create_type=False,
)
sender_type = postgresql.ENUM(
    "reporter",
    "handler",
    "system",
    name="sender_type",
    create_type=False,
)
user_role = postgresql.ENUM(
    "system_admin",
    "tenant_admin",
    "handler",
    "reviewer",
    "auditor",
    name="user_role",
    create_type=False,
)
audit_action = postgresql.ENUM(
    "case.created",
    "case.status_changed",
    "case.assigned",
    "case.priority_changed",
    "case.deleted",
    "message.sent",
    "message.read",
    "attachment.uploaded",
    "attachment.downloaded",
    "identity.disclosure_requested",
    "identity.disclosure_approved",
    "identity.disclosure_rejected",
    "identity.disclosed",
    "user.created",
    "user.updated",
    "user.deactivated",
    "user.login",
    "user.logout",
    "tenant.created",
    "tenant.updated",
    "tenant.deactivated",
    "category.created",
    "category.updated",
    "category.deleted",
    "mailbox.login",
    "mailbox.login_failed",
    "magic_link.requested",
    "magic_link.used",
    "data_retention.executed",
    "system.error",
    name="audit_action",
    create_type=False,
)
disclosure_status = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "expired",
    name="disclosure_status",
    create_type=False,
)

# Tenant-scoped tables that need RLS policies.
_TENANT_RLS_TABLES = [
    "reports",
    "messages",
    "attachments",
    "users",
    "audit_logs",
    "category_translations",
    "identity_disclosures",
]


def upgrade() -> None:
    """Apply schema changes."""

    # ── 1. Extensions ────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── 2. Application role (non-superuser for RLS) ──────────
    # The role may already exist if init-db-users.sh ran first;
    # use DO $$ … IF NOT EXISTS to be idempotent.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user
                    LOGIN
                    PASSWORD ''' || current_setting('app.db_app_password', true) || '''
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE;
            END IF;
        END $$;
    """)

    # ── 3. Enum types ────────────────────────────────────────
    channel_type.create(op.get_bind(), checkfirst=True)
    report_status.create(op.get_bind(), checkfirst=True)
    priority_level.create(op.get_bind(), checkfirst=True)
    supply_chain_tier.create(op.get_bind(), checkfirst=True)
    reporter_relationship.create(op.get_bind(), checkfirst=True)
    lksg_category.create(op.get_bind(), checkfirst=True)
    sender_type.create(op.get_bind(), checkfirst=True)
    user_role.create(op.get_bind(), checkfirst=True)
    audit_action.create(op.get_bind(), checkfirst=True)
    disclosure_status.create(op.get_bind(), checkfirst=True)

    # ── 4. Tables (dependency order) ─────────────────────────

    # 4a. tenants — root table, no foreign keys
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "slug",
            sa.String(63),
            nullable=False,
            unique=True,
            comment="URL-safe tenant identifier",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="Organisation display name",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Inactive tenants are locked out",
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Tenant-specific settings (branding, SMTP, languages, retention)",
        ),
        sa.Column(
            "dek_ciphertext",
            sa.Text(),
            nullable=False,
            comment="Envelope-encrypted per-tenant DEK (hex)",
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
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # 4b. users — depends on tenants
    op.create_table(
        "users",
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
            "email",
            sa.String(255),
            nullable=False,
            comment="OIDC email address",
        ),
        sa.Column(
            "display_name",
            sa.String(255),
            nullable=False,
            comment="Human-readable name",
        ),
        sa.Column(
            "oidc_subject",
            sa.String(255),
            nullable=False,
            unique=True,
            comment="OIDC sub claim (Entra ID)",
        ),
        sa.Column(
            "role",
            user_role,
            nullable=False,
            server_default=sa.text("'reviewer'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_custodian",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Can act as identity disclosure custodian",
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
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 4c. reports — depends on tenants, users
    op.create_table(
        "reports",
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
            "case_number",
            sa.String(16),
            nullable=False,
            unique=True,
            comment="16-char case identifier shown to reporter",
        ),
        # ── Authentication
        sa.Column(
            "passphrase_hash",
            sa.String(255),
            nullable=False,
            comment="bcrypt hash of passphrase or self-chosen password",
        ),
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # ── Case metadata
        sa.Column(
            "channel",
            channel_type,
            nullable=False,
            server_default=sa.text("'hinschg'"),
        ),
        sa.Column(
            "status",
            report_status,
            nullable=False,
            server_default=sa.text("'eingegangen'"),
        ),
        sa.Column(
            "priority",
            priority_level,
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column(
            "category",
            sa.String(100),
            nullable=True,
            comment="Category key (references category_translations)",
        ),
        # ── Encrypted fields (pgcrypto BYTEA)
        sa.Column(
            "subject_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted report subject",
        ),
        sa.Column(
            "description_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted report description",
        ),
        sa.Column(
            "reporter_name_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted reporter name (non-anonymous)",
        ),
        sa.Column(
            "reporter_email_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted reporter email (non-anonymous)",
        ),
        sa.Column(
            "reporter_phone_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted reporter phone (non-anonymous)",
        ),
        # ── LkSG-extended fields
        sa.Column(
            "country",
            sa.String(3),
            nullable=True,
            comment="ISO 3166-1 alpha-3 country code (LkSG)",
        ),
        sa.Column(
            "organization",
            sa.String(255),
            nullable=True,
            comment="Reported organisation name (LkSG)",
        ),
        sa.Column(
            "supply_chain_tier",
            supply_chain_tier,
            nullable=True,
        ),
        sa.Column(
            "reporter_relationship",
            reporter_relationship,
            nullable=True,
        ),
        sa.Column(
            "lksg_category",
            lksg_category,
            nullable=True,
        ),
        # ── Case assignment
        sa.Column(
            "assigned_to",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # ── Retention
        sa.Column(
            "retention_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Auto-delete after this date (3y HinSchG, 7y LkSG)",
        ),
        # ── Language
        sa.Column(
            "language",
            sa.String(5),
            nullable=False,
            server_default=sa.text("'de'"),
            comment="Reporter's preferred language (ISO 639-1)",
        ),
        # ── Full-text search (tsvector maintained by trigger)
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            nullable=True,
            comment="tsvector for German full-text search (maintained by trigger)",
        ),
        # ── Related cases
        sa.Column(
            "related_case_numbers",
            postgresql.ARRAY(sa.String(16)),
            nullable=True,
            comment="Case numbers of related reports",
        ),
        # ── Timestamps
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
        # ── Optimistic locking
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Optimistic locking version",
        ),
        # ── Deadlines
        sa.Column(
            "confirmation_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="7-day confirmation deadline (HinSchG §28)",
        ),
        sa.Column(
            "feedback_deadline",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="3-month feedback deadline (HinSchG §28)",
        ),
        sa.Column(
            "confirmation_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "feedback_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_reports_tenant_id", "reports", ["tenant_id"])
    op.create_index("ix_reports_case_number", "reports", ["case_number"])
    op.create_index("ix_reports_channel", "reports", ["channel"])
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_category", "reports", ["category"])
    op.create_index("ix_reports_assigned_to", "reports", ["assigned_to"])

    # 4d. messages — depends on reports, tenants, users
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ── Encrypted content (pgcrypto BYTEA)
        sa.Column(
            "content_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted message body",
        ),
        # ── Sender info
        sa.Column(
            "sender_type",
            sender_type,
            nullable=False,
        ),
        sa.Column(
            "sender_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Handler/system user ID (NULL for anonymous reporter)",
        ),
        # ── Flags
        sa.Column(
            "is_internal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Internal notes visible only to handlers",
        ),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # ── Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_messages_report_id", "messages", ["report_id"])
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])

    # 4e. attachments — depends on reports, messages, tenants
    op.create_table(
        "attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
            comment="NULL for attachments from initial report submission",
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ── File metadata
        sa.Column(
            "storage_key",
            sa.String(512),
            nullable=False,
            comment="MinIO object key",
        ),
        sa.Column(
            "original_filename",
            sa.String(255),
            nullable=False,
            comment="User-provided filename",
        ),
        sa.Column(
            "content_type",
            sa.String(127),
            nullable=False,
            server_default=sa.text("'application/octet-stream'"),
            comment="MIME type",
        ),
        sa.Column(
            "file_size",
            sa.Integer(),
            nullable=False,
            comment="Original file size in bytes",
        ),
        # ── Encryption metadata
        sa.Column(
            "encryption_key_ciphertext",
            sa.String(512),
            nullable=False,
            comment="Envelope-encrypted per-file AES-256-GCM key (hex)",
        ),
        sa.Column(
            "sha256_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hash of original file",
        ),
        # ── Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_attachments_report_id", "attachments", ["report_id"])
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])
    op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])

    # 4f. audit_logs — depends on tenants (append-only)
    op.create_table(
        "audit_logs",
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
        # ── Event data
        sa.Column(
            "action",
            audit_action,
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User who performed the action (NULL for anonymous/system)",
        ),
        sa.Column(
            "actor_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'system'"),
            comment="user, reporter, or system",
        ),
        # ── Resource identification
        sa.Column(
            "resource_type",
            sa.String(50),
            nullable=False,
            comment="Type of affected resource (report, user, tenant, etc.)",
        ),
        sa.Column(
            "resource_id",
            sa.String(255),
            nullable=False,
            comment="ID of the affected resource",
        ),
        # ── Details
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Action-specific data (old/new values, reason, etc.)",
        ),
        # ── Context
        sa.Column(
            "ip_address",
            sa.String(45),
            nullable=True,
            comment="Actor IP (always NULL for reporter actions)",
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
            comment="HTTP User-Agent header",
        ),
        # ── Timestamp
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # 4g. category_translations — depends on tenants
    op.create_table(
        "category_translations",
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
        # ── Category identification
        sa.Column(
            "category_key",
            sa.String(100),
            nullable=False,
            comment="Machine-readable category identifier",
        ),
        sa.Column(
            "language",
            sa.String(5),
            nullable=False,
            comment="ISO 639-1 language code",
        ),
        # ── Translation content
        sa.Column(
            "label",
            sa.String(255),
            nullable=False,
            comment="Translated category name",
        ),
        sa.Column(
            "description",
            sa.String(1000),
            nullable=True,
            comment="Optional help text for the category",
        ),
        # ── Display
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Display order (ascending)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # ── Timestamps
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
        # ── Unique constraint
        sa.UniqueConstraint(
            "tenant_id",
            "category_key",
            "language",
            name="uq_category_tenant_key_lang",
        ),
    )
    op.create_index(
        "ix_category_translations_tenant_id",
        "category_translations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_category_translations_category_key",
        "category_translations",
        ["category_key"],
    )

    # 4h. identity_disclosures — depends on reports, tenants, users
    op.create_table(
        "identity_disclosures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ── Request
        sa.Column(
            "requester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="Handler who requested disclosure",
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            comment="Justification for identity disclosure request",
        ),
        # ── Decision
        sa.Column(
            "status",
            disclosure_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "custodian_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Custodian who decided on the request",
        ),
        sa.Column(
            "decision_reason",
            sa.Text(),
            nullable=True,
            comment="Custodian's reason for approval or rejection",
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # ── Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_identity_disclosures_report_id",
        "identity_disclosures",
        ["report_id"],
    )
    op.create_index(
        "ix_identity_disclosures_tenant_id",
        "identity_disclosures",
        ["tenant_id"],
    )
    op.create_index(
        "ix_identity_disclosures_status",
        "identity_disclosures",
        ["status"],
    )

    # ── 5. tsvector GIN index for German full-text search ────
    # The search_vector column is maintained by a trigger that
    # computes tsvector from searchable (non-encrypted) fields.
    op.execute("""
        CREATE INDEX ix_reports_search_vector
            ON reports
            USING GIN (search_vector);
    """)

    # Trigger function to auto-update search_vector from non-encrypted
    # searchable fields (case_number, category, organization, country).
    op.execute("""
        CREATE OR REPLACE FUNCTION reports_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('german', coalesce(NEW.case_number, '')), 'A') ||
                setweight(to_tsvector('german', coalesce(NEW.category, '')), 'B') ||
                setweight(to_tsvector('german', coalesce(NEW.organization, '')), 'C') ||
                setweight(to_tsvector('german', coalesce(NEW.country, '')), 'D');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_reports_search_vector_update
            BEFORE INSERT OR UPDATE ON reports
            FOR EACH ROW
            EXECUTE FUNCTION reports_search_vector_update();
    """)

    # ── 6. Audit log immutability (block UPDATE and DELETE) ──
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs table is append-only: % operations are forbidden',
                TG_OP;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION audit_logs_immutable();
    """)

    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION audit_logs_immutable();
    """)

    # ── 7. Row-Level Security on tenant-scoped tables ────────
    # Enable RLS, create tenant_isolation policy, FORCE RLS
    # even for the table owner.
    for table in _TENANT_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
        """)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # ── 8. Grant permissions to app_user ─────────────────────
    # Use dynamic SQL because GRANT doesn't accept current_database()
    # as a function call — it expects a literal name.
    op.execute("""
        DO $$ BEGIN
            EXECUTE format(
                'GRANT CONNECT ON DATABASE %I TO app_user',
                current_database()
            );
        END $$;
    """)
    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON ALL TABLES IN SCHEMA public TO app_user"
    )
    # Defense-in-depth: revoke destructive operations on audit_logs
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM app_user")
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user"
    )
    # Ensure future tables/sequences created by migrations are also accessible.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO app_user"
    )

    # ── 9. updated_at auto-update trigger ────────────────────
    # Shared trigger function for tables with updated_at columns.
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in ("tenants", "reports", "users", "category_translations"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    """Revert schema changes."""

    # ── Remove updated_at triggers ───────────────────────────
    for table in ("tenants", "reports", "users", "category_translations"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")

    # ── Revoke permissions from app_user ─────────────────────
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM app_user"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE "
        "ON ALL TABLES IN SCHEMA public FROM app_user"
    )
    op.execute("REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM app_user")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_user")

    # ── Remove RLS policies ──────────────────────────────────
    for table in _TENANT_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Remove audit log immutability triggers ───────────────
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")

    # ── Remove search vector trigger and index ───────────────
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reports_search_vector_update ON reports"
    )
    op.execute("DROP FUNCTION IF EXISTS reports_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS ix_reports_search_vector")

    # ── Drop tables (reverse dependency order) ───────────────
    op.drop_table("identity_disclosures")
    op.drop_table("category_translations")
    op.drop_table("audit_logs")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("reports")
    op.drop_table("users")
    op.drop_table("tenants")

    # ── Drop enum types ──────────────────────────────────────
    disclosure_status.drop(op.get_bind(), checkfirst=True)
    audit_action.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
    sender_type.drop(op.get_bind(), checkfirst=True)
    lksg_category.drop(op.get_bind(), checkfirst=True)
    reporter_relationship.drop(op.get_bind(), checkfirst=True)
    supply_chain_tier.drop(op.get_bind(), checkfirst=True)
    priority_level.drop(op.get_bind(), checkfirst=True)
    report_status.drop(op.get_bind(), checkfirst=True)
    channel_type.drop(op.get_bind(), checkfirst=True)

    # ── Drop app_user role ───────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                DROP ROLE app_user;
            END IF;
        END $$;
    """)

    # ── Drop pgcrypto extension ──────────────────────────────
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
