"""Hinweisgebersystem -- SubStatus ORM Model.

Stores per-tenant configurable sub-statuses that refine the five
fixed HinSchG case lifecycle statuses (``ReportStatus``).  Each
sub-status is linked to a parent status and can be toggled active/
inactive without data loss.

Example: The parent status ``in_bearbeitung`` might have sub-statuses
like "Waiting for external input", "Under legal review", "Escalated
to management".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.report import ReportStatus

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class SubStatus(Base):
    """Configurable sub-status for a given parent case status.

    Attributes
    ----------
    id : uuid
        Primary key.
    tenant_id : uuid
        Owning tenant (CASCADE on delete).
    parent_status : ReportStatus
        The fixed HinSchG lifecycle status this sub-status belongs to.
    name : str
        Human-readable sub-status label (e.g. "Waiting for feedback").
    display_order : int
        Sort order within the parent status group (ascending).
    is_default : bool
        Whether this sub-status is automatically assigned when a
        report transitions to the parent status.
    is_active : bool
        Inactive sub-statuses are hidden from new assignments but
        preserved on existing reports.
    created_at : datetime
        Timestamp of creation (server-side default).
    """

    __tablename__ = "sub_statuses"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "parent_status",
            "name",
            name="uq_substatus_tenant_parent_name",
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

    # -- Parent status link -----------------------------------------
    parent_status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status", create_constraint=False),
        nullable=False,
        index=True,
        comment="Fixed HinSchG lifecycle status this sub-status refines",
    )

    # -- Sub-status identification ----------------------------------
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable sub-status label",
    )

    # -- Display ----------------------------------------------------
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Sort order within parent status group (ascending)",
    )
    is_default: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="false",
        comment="Auto-assign when report transitions to parent status",
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="true",
    )

    # -- Timestamps -------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # -- Relationships ----------------------------------------------
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="sub_statuses",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<SubStatus name={self.name!r} "
            f"parent={self.parent_status.value!r} "
            f"active={self.is_active}>"
        )
