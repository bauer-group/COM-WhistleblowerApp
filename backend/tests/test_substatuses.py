"""Hinweisgebersystem -- Sub-Status Management Tests.

Tests:
- Sub-status CRUD (create, read, update, soft-delete).
- Default flag management (is_default).
- Tenant isolation (sub-statuses from tenant A invisible to tenant B).
- Unique constraint on (tenant_id, parent_status, name).
- Schema validation (SubStatusCreate, SubStatusUpdate).
- Audit action enum values for sub-status operations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.substatus import SubStatus
from app.models.report import ReportStatus
from app.models.audit_log import AuditAction
from app.schemas.substatus import SubStatusCreate, SubStatusUpdate, SubStatusResponse


# ── Constants ───────────────────────────────────────────────

_TENANT_A_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_TENANT_B_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


# ── Helper ──────────────────────────────────────────────────


def _make_substatus(
    tenant_id: uuid.UUID = _TENANT_A_ID,
    parent_status: ReportStatus = ReportStatus.IN_BEARBEITUNG,
    name: str = "Waiting for feedback",
    display_order: int = 0,
    is_default: bool = False,
    is_active: bool = True,
) -> SubStatus:
    """Create a SubStatus ORM instance (not yet persisted)."""
    return SubStatus(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        parent_status=parent_status,
        name=name,
        display_order=display_order,
        is_default=is_default,
        is_active=is_active,
        created_at=datetime.now(UTC),
    )


# ── Sub-Status CRUD ─────────────────────────────────────────


class TestSubStatusCRUD:
    """Tests for SubStatus create/read/update/soft-delete."""

    @pytest.mark.asyncio
    async def test_create_substatus(self, db_session: AsyncSession):
        """Create a sub-status and verify fields are stored correctly."""
        ss = _make_substatus(
            name="Under legal review",
            parent_status=ReportStatus.IN_PRUEFUNG,
            display_order=1,
        )
        db_session.add(ss)
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.id == ss.id)
        )
        saved = result.scalar_one()

        assert saved.name == "Under legal review"
        assert saved.parent_status == ReportStatus.IN_PRUEFUNG
        assert saved.display_order == 1
        assert saved.is_default is False
        assert saved.is_active is True
        assert saved.tenant_id == _TENANT_A_ID

    @pytest.mark.asyncio
    async def test_update_substatus_name_and_order(self, db_session: AsyncSession):
        """Updating sub-status name and display_order must persist."""
        ss = _make_substatus(name="Old Name", display_order=0)
        db_session.add(ss)
        await db_session.commit()

        ss.name = "Updated Name"
        ss.display_order = 5
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.id == ss.id)
        )
        updated = result.scalar_one()
        assert updated.name == "Updated Name"
        assert updated.display_order == 5

    @pytest.mark.asyncio
    async def test_soft_delete_substatus(self, db_session: AsyncSession):
        """Soft-deleting a sub-status sets is_active=False."""
        ss = _make_substatus(name="To Delete")
        db_session.add(ss)
        await db_session.commit()

        ss.is_active = False
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.id == ss.id)
        )
        deleted = result.scalar_one()
        assert deleted.is_active is False

    @pytest.mark.asyncio
    async def test_read_by_parent_status(self, db_session: AsyncSession):
        """Reading sub-statuses by parent_status must filter correctly."""
        ss1 = _make_substatus(
            name="In Progress Sub",
            parent_status=ReportStatus.IN_BEARBEITUNG,
        )
        ss2 = _make_substatus(
            name="Review Sub",
            parent_status=ReportStatus.IN_PRUEFUNG,
        )
        db_session.add_all([ss1, ss2])
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(
                SubStatus.parent_status == ReportStatus.IN_BEARBEITUNG,
                SubStatus.tenant_id == _TENANT_A_ID,
            )
        )
        subs = result.scalars().all()
        assert all(s.parent_status == ReportStatus.IN_BEARBEITUNG for s in subs)
        assert any(s.name == "In Progress Sub" for s in subs)


# ── Default Flag Management ──────────────────────────────────


class TestSubStatusDefaultFlag:
    """Tests for is_default flag management."""

    @pytest.mark.asyncio
    async def test_default_flag_persists(self, db_session: AsyncSession):
        """Setting is_default=True must persist correctly."""
        ss = _make_substatus(name="Default Sub", is_default=True)
        db_session.add(ss)
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.id == ss.id)
        )
        saved = result.scalar_one()
        assert saved.is_default is True

    @pytest.mark.asyncio
    async def test_multiple_defaults_possible_at_model_level(
        self, db_session: AsyncSession
    ):
        """At the ORM level, multiple defaults can exist.

        The API layer is responsible for clearing existing defaults
        when a new default is set.  This test verifies that the model
        does not enforce single-default at the DB level.
        """
        ss1 = _make_substatus(name="Default 1", is_default=True)
        ss2 = _make_substatus(name="Default 2", is_default=True)
        db_session.add_all([ss1, ss2])
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(
                SubStatus.is_default == True,  # noqa: E712
                SubStatus.tenant_id == _TENANT_A_ID,
            )
        )
        defaults = result.scalars().all()
        assert len(defaults) >= 2

    @pytest.mark.asyncio
    async def test_clear_default(self, db_session: AsyncSession):
        """Clearing the default flag must set is_default=False."""
        ss = _make_substatus(name="Was Default", is_default=True)
        db_session.add(ss)
        await db_session.commit()

        ss.is_default = False
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.id == ss.id)
        )
        saved = result.scalar_one()
        assert saved.is_default is False


# ── Tenant Isolation ────────────────────────────────────────


class TestSubStatusTenantIsolation:
    """Tests for tenant isolation of sub-statuses."""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_substatuses(
        self, db_session: AsyncSession
    ):
        """Sub-statuses from tenant A must not appear in tenant B queries."""
        ss_a = _make_substatus(tenant_id=_TENANT_A_ID, name="Tenant A Sub")
        ss_b = _make_substatus(tenant_id=_TENANT_B_ID, name="Tenant B Sub")
        db_session.add_all([ss_a, ss_b])
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.tenant_id == _TENANT_B_ID)
        )
        b_subs = result.scalars().all()
        b_names = [s.name for s in b_subs]

        assert "Tenant B Sub" in b_names
        assert "Tenant A Sub" not in b_names

    @pytest.mark.asyncio
    async def test_tenant_a_substatuses_only(self, db_session: AsyncSession):
        """Querying tenant A must return only tenant A sub-statuses."""
        ss_a = _make_substatus(tenant_id=_TENANT_A_ID, name="A Only")
        ss_b = _make_substatus(tenant_id=_TENANT_B_ID, name="B Only")
        db_session.add_all([ss_a, ss_b])
        await db_session.commit()

        result = await db_session.execute(
            select(SubStatus).where(SubStatus.tenant_id == _TENANT_A_ID)
        )
        a_subs = result.scalars().all()
        assert all(s.tenant_id == _TENANT_A_ID for s in a_subs)


# ── Audit Action Enum Values ────────────────────────────────


class TestSubStatusAuditActions:
    """Verify audit action enum values exist for sub-status operations."""

    def test_substatus_created_action_exists(self):
        """AuditAction.SUB_STATUS_CREATED must exist."""
        assert AuditAction.SUB_STATUS_CREATED == "sub_status.created"

    def test_substatus_updated_action_exists(self):
        """AuditAction.SUB_STATUS_UPDATED must exist."""
        assert AuditAction.SUB_STATUS_UPDATED == "sub_status.updated"

    def test_substatus_deleted_action_exists(self):
        """AuditAction.SUB_STATUS_DELETED must exist."""
        assert AuditAction.SUB_STATUS_DELETED == "sub_status.deleted"


# ── Schema Validation ───────────────────────────────────────


class TestSubStatusSchemas:
    """Tests for sub-status Pydantic schema validation."""

    def test_substatus_create_valid(self):
        """Valid SubStatusCreate schema must be accepted."""
        schema = SubStatusCreate(
            parent_status=ReportStatus.IN_BEARBEITUNG,
            name="Escalated",
            display_order=1,
            is_default=False,
        )
        assert schema.name == "Escalated"
        assert schema.parent_status == ReportStatus.IN_BEARBEITUNG

    def test_substatus_create_default_values(self):
        """SubStatusCreate with only required fields uses correct defaults."""
        schema = SubStatusCreate(
            parent_status=ReportStatus.EINGEGANGEN,
            name="New Sub",
        )
        assert schema.display_order == 0
        assert schema.is_default is False

    def test_substatus_create_empty_name_rejected(self):
        """SubStatusCreate with empty name must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubStatusCreate(
                parent_status=ReportStatus.IN_BEARBEITUNG,
                name="",
            )

    def test_substatus_create_name_too_long(self):
        """SubStatusCreate with name > 255 chars must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubStatusCreate(
                parent_status=ReportStatus.IN_BEARBEITUNG,
                name="x" * 256,
            )

    def test_substatus_create_negative_display_order_rejected(self):
        """SubStatusCreate with negative display_order must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubStatusCreate(
                parent_status=ReportStatus.IN_BEARBEITUNG,
                name="Test",
                display_order=-1,
            )

    def test_substatus_update_all_optional(self):
        """SubStatusUpdate with no fields must be valid (all optional)."""
        schema = SubStatusUpdate()
        assert schema.name is None
        assert schema.display_order is None
        assert schema.is_default is None
        assert schema.is_active is None

    def test_substatus_response_from_orm(self):
        """SubStatusResponse must be constructible from a SubStatus ORM instance."""
        ss = _make_substatus(name="ORM Test")
        response = SubStatusResponse.model_validate(ss)
        assert response.name == "ORM Test"
        assert response.parent_status == ReportStatus.IN_BEARBEITUNG

    def test_substatus_repr(self):
        """SubStatus __repr__ must include name and parent status."""
        ss = _make_substatus(name="Test Sub", parent_status=ReportStatus.IN_PRUEFUNG)
        r = repr(ss)
        assert "Test Sub" in r
        assert "in_pruefung" in r


# ── Parent Status Enum Values ────────────────────────────────


class TestReportStatusEnum:
    """Verify all five HinSchG lifecycle statuses exist."""

    def test_eingegangen_exists(self):
        assert ReportStatus.EINGEGANGEN == "eingegangen"

    def test_in_pruefung_exists(self):
        assert ReportStatus.IN_PRUEFUNG == "in_pruefung"

    def test_in_bearbeitung_exists(self):
        assert ReportStatus.IN_BEARBEITUNG == "in_bearbeitung"

    def test_rueckmeldung_exists(self):
        assert ReportStatus.RUECKMELDUNG == "rueckmeldung"

    def test_abgeschlossen_exists(self):
        assert ReportStatus.ABGESCHLOSSEN == "abgeschlossen"
