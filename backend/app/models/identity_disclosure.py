"""Hinweisgebersystem – IdentityDisclosure ORM Model.

Implements the 4-eyes principle for accessing sealed reporter identity
data.  When a reporter opts to seal their identity, disclosure requires
approval by both a Custodian and a Handler.  Every step of the
disclosure workflow is logged in the audit trail.

Workflow:
1. Handler requests disclosure with a reason.
2. Custodian approves or rejects the request.
3. If approved, identity fields are decrypted and shown.
4. Every disclosure event is logged in ``audit_logs``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.report import Report


# ── Enums ─────────────────────────────────────────────────────


class DisclosureStatus(str, enum.Enum):
    """Status of an identity disclosure request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ── IdentityDisclosure Model ─────────────────────────────────


class IdentityDisclosure(Base):
    """Identity disclosure request / approval record.

    Attributes
    ----------
    requester_id : uuid
        The handler who requested the disclosure.
    custodian_id : uuid | None
        The custodian who approved or rejected the request.
    reason : str
        Mandatory justification for requesting disclosure.
    status : DisclosureStatus
        Current state of the disclosure request.
    decided_at : datetime | None
        When the custodian made their decision.
    decision_reason : str | None
        Optional reason for approval or rejection by the custodian.
    """

    __tablename__ = "identity_disclosures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Request ───────────────────────────────────────────────
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Handler who requested disclosure",
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Justification for identity disclosure request",
    )

    # ── Decision ──────────────────────────────────────────────
    status: Mapped[DisclosureStatus] = mapped_column(
        Enum(DisclosureStatus, name="disclosure_status", create_constraint=True),
        nullable=False,
        default=DisclosureStatus.PENDING,
        index=True,
    )
    custodian_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Custodian who decided on the request",
    )
    decision_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Custodian's reason for approval or rejection",
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────
    report: Mapped[Report] = relationship(
        "Report",
        back_populates="identity_disclosures",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<IdentityDisclosure report_id={self.report_id!r} "
            f"status={self.status.value!r}>"
        )
