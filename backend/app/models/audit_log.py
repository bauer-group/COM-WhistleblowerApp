"""Hinweisgebersystem – AuditLog ORM Model (Append-Only).

Immutable audit trail for all security-relevant actions in the system.
The underlying database table has triggers or rules that block UPDATE
and DELETE operations, ensuring the audit trail cannot be tampered with.

Every state change, access event, and administrative action is recorded
with the actor, resource, old/new values, and timestamp.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.tenant import Tenant


# ── Enums ─────────────────────────────────────────────────────


class AuditAction(str, enum.Enum):
    """Categorised audit event types."""

    # Case lifecycle
    CASE_CREATED = "case.created"
    CASE_STATUS_CHANGED = "case.status_changed"
    CASE_ASSIGNED = "case.assigned"
    CASE_PRIORITY_CHANGED = "case.priority_changed"
    CASE_DELETED = "case.deleted"

    # Messages
    MESSAGE_SENT = "message.sent"
    MESSAGE_READ = "message.read"

    # Attachments
    ATTACHMENT_UPLOADED = "attachment.uploaded"
    ATTACHMENT_DOWNLOADED = "attachment.downloaded"

    # Identity disclosure (4-eyes)
    IDENTITY_DISCLOSURE_REQUESTED = "identity.disclosure_requested"
    IDENTITY_DISCLOSURE_APPROVED = "identity.disclosure_approved"
    IDENTITY_DISCLOSURE_REJECTED = "identity.disclosure_rejected"
    IDENTITY_DISCLOSED = "identity.disclosed"

    # User management
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"

    # Tenant management
    TENANT_CREATED = "tenant.created"
    TENANT_UPDATED = "tenant.updated"
    TENANT_DEACTIVATED = "tenant.deactivated"

    # Category management
    CATEGORY_CREATED = "category.created"
    CATEGORY_UPDATED = "category.updated"
    CATEGORY_DELETED = "category.deleted"

    # Label management
    LABEL_CREATED = "label.created"
    LABEL_UPDATED = "label.updated"
    LABEL_DELETED = "label.deleted"
    LABEL_ASSIGNED = "label.assigned"
    LABEL_REMOVED = "label.removed"

    # Sub-status management
    SUB_STATUS_CREATED = "sub_status.created"
    SUB_STATUS_UPDATED = "sub_status.updated"
    SUB_STATUS_DELETED = "sub_status.deleted"

    # TOTP Two-Factor Authentication
    TOTP_ENABLED = "totp.enabled"
    TOTP_DISABLED = "totp.disabled"
    TOTP_RESET = "totp.reset"
    TOTP_CHALLENGE_FAILED = "totp.challenge_failed"

    # PGP Key Management
    PGP_KEY_UPLOADED = "pgp.key_uploaded"
    PGP_KEY_DELETED = "pgp.key_deleted"
    PGP_KEY_EXPIRED = "pgp.key_expired"

    # Reporter access
    MAILBOX_LOGIN = "mailbox.login"
    MAILBOX_LOGIN_FAILED = "mailbox.login_failed"
    MAGIC_LINK_REQUESTED = "magic_link.requested"
    MAGIC_LINK_USED = "magic_link.used"

    # Data retention
    DATA_RETENTION_EXECUTED = "data_retention.executed"

    # System
    SYSTEM_ERROR = "system.error"


# ── AuditLog Model ────────────────────────────────────────────


class AuditLog(Base):
    """Append-only audit log entry.

    The database enforces immutability via triggers that block
    UPDATE and DELETE on the ``audit_logs`` table.

    Attributes
    ----------
    action : AuditAction
        The type of event being logged.
    actor_id : uuid | None
        The user who performed the action (NULL for anonymous/system).
    actor_type : str
        ``"user"``, ``"reporter"``, or ``"system"``.
    resource_type : str
        The type of resource affected (e.g. ``"report"``, ``"user"``).
    resource_id : str
        The ID of the affected resource.
    details : dict | None
        JSONB object with action-specific data, e.g. old/new status
        values, reason for disclosure, etc.
    ip_address : str | None
        IP address of the actor.  Always NULL for reporter actions
        to protect anonymity.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Event data ────────────────────────────────────────────
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", create_constraint=True),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="User who performed the action (NULL for anonymous/system)",
    )
    actor_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="system",
        comment="user, reporter, or system",
    )

    # ── Resource identification ───────────────────────────────
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of affected resource (report, user, tenant, etc.)",
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="ID of the affected resource",
    )

    # ── Details ───────────────────────────────────────────────
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Action-specific data (old/new values, reason, etc.)",
    )

    # ── Context ───────────────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="Actor IP (always NULL for reporter actions)",
    )
    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="HTTP User-Agent header",
    )

    # ── Timestamp ─────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # ── Relationships ─────────────────────────────────────────
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="audit_logs",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog action={self.action.value!r} "
            f"resource={self.resource_type}/{self.resource_id}>"
        )
