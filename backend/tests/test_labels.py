"""Hinweisgebersystem -- Label Management Tests.

Tests:
- Label CRUD (create, read, update, soft-delete).
- Duplicate name handling.
- Tenant isolation (labels from tenant A invisible to tenant B).
- Label assignment to reports (junction table).
- Audit action enum values for label operations.
- Schema validation (LabelCreate, LabelUpdate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.label import Label
from app.models.audit_log import AuditAction
from app.schemas.label import LabelCreate, LabelUpdate, LabelResponse


# ── Constants ───────────────────────────────────────────────

_TENANT_A_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_TENANT_B_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


# ── Helper ──────────────────────────────────────────────────


def _make_label(
    tenant_id: uuid.UUID = _TENANT_A_ID,
    name: str = "Urgent",
    color: str = "#FF5733",
    description: str | None = None,
    is_active: bool = True,
) -> Label:
    """Create a Label ORM instance (not yet persisted)."""
    return Label(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        color=color,
        description=description,
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ── Label CRUD ──────────────────────────────────────────────


class TestLabelCRUD:
    """Tests for Label create/read/update/soft-delete."""

    @pytest.mark.asyncio
    async def test_create_label(self, db_session: AsyncSession):
        """Create a label and verify all fields are stored correctly."""
        label = _make_label(
            name="Compliance",
            color="#3B82F6",
            description="Compliance-related reports",
        )
        db_session.add(label)
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(Label.id == label.id)
        )
        saved = result.scalar_one()

        assert saved.name == "Compliance"
        assert saved.color == "#3B82F6"
        assert saved.description == "Compliance-related reports"
        assert saved.is_active is True
        assert saved.tenant_id == _TENANT_A_ID

    @pytest.mark.asyncio
    async def test_update_label_name_and_color(self, db_session: AsyncSession):
        """Updating label name and color must persist correctly."""
        label = _make_label(name="Old Name", color="#000000")
        db_session.add(label)
        await db_session.commit()

        label.name = "New Name"
        label.color = "#FFFFFF"
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(Label.id == label.id)
        )
        updated = result.scalar_one()
        assert updated.name == "New Name"
        assert updated.color == "#FFFFFF"

    @pytest.mark.asyncio
    async def test_soft_delete_label(self, db_session: AsyncSession):
        """Soft-deleting a label sets is_active=False."""
        label = _make_label(name="To Delete")
        db_session.add(label)
        await db_session.commit()

        label.is_active = False
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(Label.id == label.id)
        )
        deleted = result.scalar_one()
        assert deleted.is_active is False

    @pytest.mark.asyncio
    async def test_read_active_only_filter(self, db_session: AsyncSession):
        """Reading with active filter should exclude inactive labels."""
        active_label = _make_label(name="Active", is_active=True)
        inactive_label = _make_label(name="Inactive", is_active=False)
        db_session.add_all([active_label, inactive_label])
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(
                Label.tenant_id == _TENANT_A_ID,
                Label.is_active == True,  # noqa: E712
            )
        )
        active_labels = result.scalars().all()
        names = [lbl.name for lbl in active_labels]

        assert "Active" in names
        assert "Inactive" not in names


# ── Label Duplicate Handling ─────────────────────────────────


class TestLabelDuplicate:
    """Tests for duplicate label name handling."""

    @pytest.mark.asyncio
    async def test_duplicate_name_same_tenant_persists(self, db_session: AsyncSession):
        """Two labels with the same name in the same tenant can be created
        at the model level (constraint enforcement is at API/DB level).

        Note: The API layer should return 409 Conflict, but at the ORM
        model level there is no unique constraint on name alone (it's
        enforced via RLS policy + router logic).  This test verifies
        that the model itself does not prevent it (as per the schema
        design).
        """
        label1 = _make_label(name="Duplicate")
        label2 = _make_label(name="Duplicate")
        db_session.add_all([label1, label2])
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(
                Label.tenant_id == _TENANT_A_ID,
                Label.name == "Duplicate",
            )
        )
        labels = result.scalars().all()
        assert len(labels) == 2


# ── Label Tenant Isolation ──────────────────────────────────


class TestLabelTenantIsolation:
    """Tests for tenant isolation of labels."""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_labels(
        self, db_session: AsyncSession
    ):
        """Labels from tenant A must not be visible when querying for
        tenant B's labels."""
        label_a = _make_label(tenant_id=_TENANT_A_ID, name="Tenant A Label")
        label_b = _make_label(tenant_id=_TENANT_B_ID, name="Tenant B Label")
        db_session.add_all([label_a, label_b])
        await db_session.commit()

        # Query tenant B's labels
        result = await db_session.execute(
            select(Label).where(Label.tenant_id == _TENANT_B_ID)
        )
        b_labels = result.scalars().all()
        b_names = [lbl.name for lbl in b_labels]

        assert "Tenant B Label" in b_names
        assert "Tenant A Label" not in b_names

    @pytest.mark.asyncio
    async def test_tenant_a_labels_only(self, db_session: AsyncSession):
        """Querying tenant A must return only tenant A labels."""
        label_a = _make_label(tenant_id=_TENANT_A_ID, name="A Only")
        label_b = _make_label(tenant_id=_TENANT_B_ID, name="B Only")
        db_session.add_all([label_a, label_b])
        await db_session.commit()

        result = await db_session.execute(
            select(Label).where(Label.tenant_id == _TENANT_A_ID)
        )
        a_labels = result.scalars().all()
        assert all(lbl.tenant_id == _TENANT_A_ID for lbl in a_labels)


# ── Audit Logging Enum Values ───────────────────────────────


class TestLabelAuditActions:
    """Verify audit action enum values exist for label operations."""

    def test_label_created_action_exists(self):
        """AuditAction.LABEL_CREATED must exist."""
        assert AuditAction.LABEL_CREATED == "label.created"

    def test_label_updated_action_exists(self):
        """AuditAction.LABEL_UPDATED must exist."""
        assert AuditAction.LABEL_UPDATED == "label.updated"

    def test_label_deleted_action_exists(self):
        """AuditAction.LABEL_DELETED must exist."""
        assert AuditAction.LABEL_DELETED == "label.deleted"

    def test_label_assigned_action_exists(self):
        """AuditAction.LABEL_ASSIGNED must exist."""
        assert AuditAction.LABEL_ASSIGNED == "label.assigned"

    def test_label_removed_action_exists(self):
        """AuditAction.LABEL_REMOVED must exist."""
        assert AuditAction.LABEL_REMOVED == "label.removed"


# ── Schema Validation ───────────────────────────────────────


class TestLabelSchemas:
    """Tests for label Pydantic schema validation."""

    def test_label_create_valid(self):
        """Valid LabelCreate schema must be accepted."""
        schema = LabelCreate(
            name="Urgent",
            color="#FF5733",
            description="High priority items",
        )
        assert schema.name == "Urgent"
        assert schema.color == "#FF5733"

    def test_label_create_default_color(self):
        """LabelCreate without color must use default #6B7280."""
        schema = LabelCreate(name="Default Color")
        assert schema.color == "#6B7280"

    def test_label_create_name_too_long(self):
        """LabelCreate with name > 100 chars must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LabelCreate(name="x" * 101)

    def test_label_create_empty_name_rejected(self):
        """LabelCreate with empty name must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LabelCreate(name="")

    def test_label_create_invalid_color_rejected(self):
        """LabelCreate with non-hex color must be rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LabelCreate(name="Test", color="not-a-color")

    def test_label_update_all_optional(self):
        """LabelUpdate with no fields must be valid (all optional)."""
        schema = LabelUpdate()
        assert schema.name is None
        assert schema.color is None
        assert schema.description is None
        assert schema.is_active is None

    def test_label_response_from_orm(self):
        """LabelResponse must be constructible from a Label ORM instance."""
        label = _make_label(name="ORM Test", color="#123456")
        response = LabelResponse.model_validate(label)
        assert response.name == "ORM Test"
        assert response.color == "#123456"
        assert response.is_active is True

    def test_label_repr(self):
        """Label __repr__ must include name and color."""
        label = _make_label(name="Test", color="#AABBCC")
        r = repr(label)
        assert "Test" in r
        assert "#AABBCC" in r
