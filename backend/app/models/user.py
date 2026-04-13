"""Hinweisgebersystem – User ORM Model.

Backend users (handlers, admins, auditors) who authenticate via OIDC
(Microsoft Entra ID).  The email from the OIDC token is mapped to the
internal role table for RBAC.

This model does NOT represent anonymous reporters — reporters are
identified only by their case number and passphrase hash.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.types import PGPString

if TYPE_CHECKING:
    from app.models.tenant import Tenant


# ── Enums ─────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    """Role-Based Access Control roles.

    - SYSTEM_ADMIN: Full system access (cross-tenant).
    - TENANT_ADMIN: Tenant-scoped management.
    - HANDLER: Full case access within tenant.
    - REVIEWER: Assigned cases only.
    - AUDITOR: Read-only access to audit logs.
    """

    SYSTEM_ADMIN = "system_admin"
    TENANT_ADMIN = "tenant_admin"
    HANDLER = "handler"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"


# ── User Model ────────────────────────────────────────────────


class User(Base):
    """Backend user authenticated via OIDC.

    Attributes
    ----------
    email : str
        Email address from OIDC token (unique per tenant).
    display_name : str
        Human-readable display name.
    oidc_subject : str
        OIDC ``sub`` claim (unique identifier from Entra ID).
    role : UserRole
        RBAC role determining access permissions.
    is_active : bool
        Deactivated users cannot log in.
    is_custodian : bool
        Whether this user can act as identity custodian
        (4-eyes principle for identity disclosure).
    totp_secret : str | None
        TOTP shared secret, encrypted at rest via pgcrypto (PGPString).
    totp_enabled : bool
        Whether TOTP two-factor authentication is active for this user.
    totp_verified_at : datetime | None
        Timestamp when TOTP was first verified (setup completed).
    totp_last_used_at : datetime | None
        Timestamp of the last successful TOTP verification.
    totp_backup_codes_hash : list[str] | None
        Hashed TOTP backup/recovery codes (bcrypt hashes).
    pgp_public_key : str | None
        ASCII-armored PGP public key for encrypted email notifications.
    pgp_fingerprint : str | None
        PGP key fingerprint (hex string, up to 64 chars).
    pgp_key_expires_at : datetime | None
        Expiration timestamp of the uploaded PGP key.
    """

    __tablename__ = "users"

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
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="OIDC email address",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable name",
    )
    oidc_subject: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="OIDC sub claim (Entra ID)",
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_constraint=True),
        nullable=False,
        default=UserRole.REVIEWER,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    is_custodian: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Can act as identity disclosure custodian",
    )

    # ── TOTP Two-Factor Authentication ────────────────────────
    totp_secret: Mapped[str | None] = mapped_column(
        PGPString("per_tenant_dek"),
        nullable=True,
        comment="TOTP shared secret (pgcrypto encrypted)",
    )
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether TOTP 2FA is active",
    )
    totp_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When TOTP setup was first verified",
    )
    totp_last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful TOTP verification",
    )
    totp_backup_codes_hash: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Hashed TOTP backup/recovery codes",
    )

    # ── PGP Email Encryption ──────────────────────────────────
    pgp_public_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="ASCII-armored PGP public key for encrypted notifications",
    )
    pgp_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="PGP key fingerprint (hex)",
    )
    pgp_key_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="PGP key expiration timestamp",
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="users",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<User email={self.email!r} "
            f"role={self.role.value!r} "
            f"active={self.is_active}>"
        )
