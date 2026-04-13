"""Hinweisgebersystem – Tenant ORM Model.

Each tenant represents an organisation using the whistleblower platform.
Tenants are resolved from subdomain or URL path prefix and used to scope
all data access via PostgreSQL Row-Level Security.

Tenant configuration (branding, SMTP, language, retention) is stored in
JSONB for flexibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.category_translation import CategoryTranslation
    from app.models.label import Label
    from app.models.report import Report
    from app.models.substatus import SubStatus
    from app.models.user import User


class Tenant(Base):
    """Multi-tenant organisation.

    Each tenant has its own branding, categories, SMTP config, language
    settings, and retention periods.  All tenant-scoped tables reference
    ``tenant_id`` and are filtered by RLS policies.

    Attributes
    ----------
    id : uuid
        Primary key.
    slug : str
        URL-safe identifier used in subdomain / path routing.
    name : str
        Display name of the organisation.
    is_active : bool
        Inactive tenants return 403 on all endpoints.
    config : dict
        JSONB object with tenant-specific settings:
        - ``branding``: logo_url, primary_color, accent_color
        - ``smtp``: host, port, user, password, from_address
        - ``languages``: list of enabled language codes
        - ``default_language``: fallback language code
        - ``retention_hinschg_years``: default 3
        - ``retention_lksg_years``: default 7
    dek_ciphertext : str
        Per-tenant Data Encryption Key (DEK), encrypted with the master
        key via envelope encryption.  Used as passphrase for pgcrypto
        ``pgp_sym_encrypt`` / ``pgp_sym_decrypt``.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    slug: Mapped[str] = mapped_column(
        String(63),
        unique=True,
        nullable=False,
        index=True,
        comment="URL-safe tenant identifier",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Organisation display name",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Inactive tenants are locked out",
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Tenant-specific settings (branding, SMTP, languages, retention)",
    )
    dek_ciphertext: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Envelope-encrypted per-tenant DEK (hex)",
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

    # ── Version (optimistic locking) ──────────────────────────
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    # ── Relationships ─────────────────────────────────────────
    reports: Mapped[list[Report]] = relationship(
        "Report",
        back_populates="tenant",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    users: Mapped[list[User]] = relationship(
        "User",
        back_populates="tenant",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    category_translations: Mapped[list[CategoryTranslation]] = relationship(
        "CategoryTranslation",
        back_populates="tenant",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog",
        back_populates="tenant",
        lazy="noload",
    )
    labels: Mapped[list[Label]] = relationship(
        "Label",
        back_populates="tenant",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    sub_statuses: Mapped[list[SubStatus]] = relationship(
        "SubStatus",
        back_populates="tenant",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Tenant slug={self.slug!r} active={self.is_active}>"
