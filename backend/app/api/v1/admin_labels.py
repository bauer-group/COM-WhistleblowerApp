"""Hinweisgebersystem – Admin Label Management API Endpoints.

Provides:
- **GET /admin/labels** — List all labels for the current tenant.
- **POST /admin/labels** — Create a new label.
- **GET /admin/labels/{label_id}** — Get a single label by ID.
- **PUT /admin/labels/{label_id}** — Update a label's name, colour,
  description, or active status.
- **DELETE /admin/labels/{label_id}** — Deactivate a label
  (soft delete).

Labels are tenant-scoped tags for organising and filtering reports.
Each label has a name, hex colour code, and optional description.

All endpoints require OIDC-authenticated admin users with appropriate
scopes.  Tenant isolation is enforced via Row-Level Security (RLS).

Usage::

    from app.api.v1.admin_labels import router as admin_labels_router
    api_v1_router.include_router(admin_labels_router)
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.audit_log import AuditAction
from app.models.label import Label
from app.repositories.audit_repo import AuditRepository
from app.schemas.label import (
    LabelCreate,
    LabelListResponse,
    LabelResponse,
    LabelUpdate,
)
from app.schemas.common import PaginationMeta

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/labels", tags=["admin-labels"])


# ── GET /admin/labels ────────────────────────────────────────


@router.get(
    "",
    response_model=LabelListResponse,
    status_code=status.HTTP_200_OK,
    summary="List labels for the current tenant",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_labels(
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    active_only: bool = Query(
        default=False,
        description="If true, only return active labels.",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=50, ge=1, le=100, description="Items per page (max 100)."
    ),
) -> LabelListResponse:
    """List all labels for the current tenant.

    Returns labels sorted by name.  Optionally filters to only
    active labels (for assignment dropdowns).

    Requires ``cases:read`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN, REVIEWER, AUDITOR).
    """
    stmt = select(Label).where(Label.tenant_id == tenant_id)

    if active_only:
        stmt = stmt.where(Label.is_active.is_(True))

    stmt = stmt.order_by(Label.name.asc())

    # Count total
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(
        stmt.subquery()
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Paginate
    import math

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    labels = list(result.scalars().all())

    logger.info(
        "admin_labels_listed",
        tenant_id=str(tenant_id),
        total=total,
        user_email=user.email,
    )

    return LabelListResponse(
        items=[LabelResponse.model_validate(lbl) for lbl in labels],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


# ── POST /admin/labels ──────────────────────────────────────


@router.post(
    "",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new label",
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "Label with this name already exists"},
    },
)
async def create_label(
    body: LabelCreate,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> LabelResponse:
    """Create a new label for the current tenant.

    The label name must be unique within the tenant.  A hex colour
    code and optional description can be provided.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    # Check for duplicate name within tenant
    existing_stmt = select(Label).where(
        Label.tenant_id == tenant_id,
        Label.name == body.name,
    )
    existing_result = await db.execute(existing_stmt)
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A label with name '{body.name}' already exists.",
        )

    label = Label(
        tenant_id=tenant_id,
        name=body.name,
        color=body.color,
        description=body.description,
    )
    db.add(label)
    await db.flush()
    await db.refresh(label)

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.LABEL_CREATED,
        resource_type="label",
        resource_id=str(label.id),
        actor_id=user.id,
        actor_type="user",
        details={"name": body.name, "color": body.color},
    )

    await db.commit()

    logger.info(
        "admin_label_created",
        label_id=str(label.id),
        label_name=body.name,
        tenant_id=str(tenant_id),
        user_email=user.email,
    )

    return LabelResponse.model_validate(label)


# ── GET /admin/labels/{label_id} ─────────────────────────────


@router.get(
    "/{label_id}",
    response_model=LabelResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single label by ID",
    responses={
        404: {"description": "Label not found"},
    },
)
async def get_label(
    label_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> LabelResponse:
    """Get a single label by its ID.

    Returns 404 if the label does not exist or belongs to a
    different tenant.

    Requires ``cases:read`` scope.
    """
    stmt = select(Label).where(
        Label.id == label_id,
        Label.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    label = result.scalar_one_or_none()

    if label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found.",
        )

    return LabelResponse.model_validate(label)


# ── PUT /admin/labels/{label_id} ─────────────────────────────


@router.put(
    "/{label_id}",
    response_model=LabelResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a label",
    responses={
        404: {"description": "Label not found"},
        409: {"description": "Label with this name already exists"},
    },
)
async def update_label(
    label_id: uuid.UUID,
    body: LabelUpdate,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> LabelResponse:
    """Update a label's name, colour, description, or active status.

    All fields are optional -- only provided fields will be updated.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    stmt = select(Label).where(
        Label.id == label_id,
        Label.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    label = result.scalar_one_or_none()

    if label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found.",
        )

    # Check for duplicate name if name is being changed
    if body.name is not None and body.name != label.name:
        dup_stmt = select(Label).where(
            Label.tenant_id == tenant_id,
            Label.name == body.name,
            Label.id != label_id,
        )
        dup_result = await db.execute(dup_stmt)
        if dup_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A label with name '{body.name}' already exists.",
            )

    # Track changes for audit
    changes: dict[str, dict] = {}
    update_data = body.model_dump(exclude_none=True)

    for field, new_value in update_data.items():
        old_value = getattr(label, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
            setattr(label, field, new_value)

    if changes:
        await db.flush()
        await db.refresh(label)

        # Audit trail
        audit_repo = AuditRepository(db)
        await audit_repo.log(
            tenant_id=tenant_id,
            action=AuditAction.LABEL_UPDATED,
            resource_type="label",
            resource_id=str(label.id),
            actor_id=user.id,
            actor_type="user",
            details={"changes": {k: v["new"] for k, v in changes.items()}},
        )

        await db.commit()

    logger.info(
        "admin_label_updated",
        label_id=str(label_id),
        tenant_id=str(tenant_id),
        user_email=user.email,
        changes=list(changes.keys()),
    )

    return LabelResponse.model_validate(label)


# ── DELETE /admin/labels/{label_id} ──────────────────────────


@router.delete(
    "/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a label (soft delete)",
    responses={
        404: {"description": "Label not found"},
    },
)
async def delete_label(
    label_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> None:
    """Deactivate a label (soft delete).

    The label is not physically deleted -- it is marked as inactive
    so that existing report assignments are preserved.  Inactive
    labels are hidden from new assignment dropdowns.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    stmt = select(Label).where(
        Label.id == label_id,
        Label.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    label = result.scalar_one_or_none()

    if label is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label not found.",
        )

    label.is_active = False
    await db.flush()

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.LABEL_DELETED,
        resource_type="label",
        resource_id=str(label.id),
        actor_id=user.id,
        actor_type="user",
        details={"name": label.name},
    )

    await db.commit()

    logger.info(
        "admin_label_deactivated",
        label_id=str(label_id),
        label_name=label.name,
        tenant_id=str(tenant_id),
        user_email=user.email,
    )
