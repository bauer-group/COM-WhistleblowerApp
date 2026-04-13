"""Hinweisgebersystem – CategoryTranslation ORM Model.

Stores per-tenant, per-language translations for report categories.
Categories are identified by a stable ``key`` (e.g. ``"corruption"``,
``"environmental_damage"``) and translated into the tenant's enabled
languages.

The fallback chain for category display is:
  selected language → tenant default language → German (de).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class CategoryTranslation(Base):
    """Translated category label for a specific tenant and language.

    Attributes
    ----------
    category_key : str
        Stable machine-readable category identifier
        (e.g. ``"corruption"``, ``"child_labor"``).
    language : str
        ISO 639-1 language code (e.g. ``"de"``, ``"en"``).
    label : str
        Human-readable translated category name.
    description : str | None
        Optional longer description of the category (used as help text).
    sort_order : int
        Display order within the category list.
    is_active : bool
        Inactive categories are hidden from new report submissions
        but preserved for existing reports.
    """

    __tablename__ = "category_translations"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "category_key",
            "language",
            name="uq_category_tenant_key_lang",
        ),
    )

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

    # ── Category identification ───────────────────────────────
    category_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Machine-readable category identifier",
    )
    language: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        comment="ISO 639-1 language code",
    )

    # ── Translation content ───────────────────────────────────
    label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Translated category name",
    )
    description: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Optional help text for the category",
    )

    # ── Display ───────────────────────────────────────────────
    sort_order: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
        comment="Display order (ascending)",
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="true",
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

    # ── Relationships ─────────────────────────────────────────
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="category_translations",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<CategoryTranslation key={self.category_key!r} "
            f"lang={self.language!r} label={self.label!r}>"
        )
