"""Hinweisgebersystem – Label ORM Model.

Labels provide a flexible tagging system for reports, allowing case
handlers and administrators to organise and filter cases by custom
criteria (e.g. ``"Urgent"``, ``"Compliance"``, ``"Follow-up needed"``).

Each label belongs to a single tenant and can be assigned to multiple
reports via the ``report_labels`` association table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.report import Report
    from app.models.tenant import Tenant


class Label(Base):
    """Tenant-scoped label for tagging reports.

    Attributes
    ----------
    id : uuid
        Primary key.
    tenant_id : uuid
        Owning tenant (CASCADE delete).
    name : str
        Human-readable label name (e.g. ``"Urgent"``).
    color : str
        Hex colour code for UI display (e.g. ``"#FF5733"``).
    description : str | None
        Optional longer description of the label's purpose.
    is_active : bool
        Inactive labels are hidden from new assignments
        but preserved on existing reports.
    """

    __tablename__ = "labels"

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

    # ── Label data ────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Human-readable label name",
    )
    color: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default="#6B7280",
        server_default="'#6B7280'",
        comment="Hex colour code for UI display (e.g. #FF5733)",
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Optional description of the label's purpose",
    )

    # ── Status ────────────────────────────────────────────────
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
        back_populates="labels",
        lazy="selectin",
    )
    reports: Mapped[list[Report]] = relationship(
        "Report",
        secondary="report_labels",
        back_populates="labels",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Label name={self.name!r} "
            f"color={self.color!r} "
            f"active={self.is_active}>"
        )
