"""Hinweisgebersystem – Admin Sub-Status Management API Endpoints.

Provides:
- **GET /admin/substatuses** — List all sub-statuses for the current
  tenant, optionally filtered by parent status.
- **POST /admin/substatuses** — Create a new sub-status.
- **GET /admin/substatuses/{substatus_id}** — Get a single sub-status
  by ID.
- **PUT /admin/substatuses/{substatus_id}** — Update a sub-status's
  name, display order, default flag, or active status.
- **DELETE /admin/substatuses/{substatus_id}** — Deactivate a
  sub-status (soft delete).

Sub-statuses are tenant-scoped refinements of the five fixed HinSchG
case lifecycle statuses.  Each sub-status is linked to a parent
``ReportStatus`` and provides more granular tracking within that
lifecycle stage (e.g. ``"Waiting for external input"`` under
``in_bearbeitung``).

All endpoints require OIDC-authenticated admin users with appropriate
scopes.  Tenant isolation is enforced via Row-Level Security (RLS).

Usage::

    from app.api.v1.admin_substatuses import router as admin_substatuses_router
    api_v1_router.include_router(admin_substatuses_router)
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
from app.models.report import ReportStatus
from app.models.substatus import SubStatus
from app.repositories.audit_repo import AuditRepository
from app.schemas.common import PaginationMeta
from app.schemas.substatus import (
    SubStatusCreate,
    SubStatusListResponse,
    SubStatusResponse,
    SubStatusUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/substatuses", tags=["admin-substatuses"])


# ── GET /admin/substatuses ──────────────────────────────────


@router.get(
    "",
    response_model=SubStatusListResponse,
    status_code=status.HTTP_200_OK,
    summary="List sub-statuses for the current tenant",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_substatuses(
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    parent_status: ReportStatus | None = Query(
        default=None,
        description="Filter by parent status (e.g. 'in_bearbeitung').",
    ),
    active_only: bool = Query(
        default=False,
        description="If true, only return active sub-statuses.",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=50, ge=1, le=100, description="Items per page (max 100)."
    ),
) -> SubStatusListResponse:
    """List all sub-statuses for the current tenant.

    Returns sub-statuses sorted by parent status and display order.
    Optionally filters by parent status (for dropdown population)
    and/or active-only status.

    Requires ``cases:read`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN, REVIEWER, AUDITOR).
    """
    stmt = select(SubStatus).where(SubStatus.tenant_id == tenant_id)

    if parent_status is not None:
        stmt = stmt.where(SubStatus.parent_status == parent_status)

    if active_only:
        stmt = stmt.where(SubStatus.is_active.is_(True))

    stmt = stmt.order_by(
        SubStatus.parent_status.asc(),
        SubStatus.display_order.asc(),
        SubStatus.name.asc(),
    )

    # Count total
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Paginate
    import math

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    substatuses = list(result.scalars().all())

    logger.info(
        "admin_substatuses_listed",
        tenant_id=str(tenant_id),
        total=total,
        parent_status=parent_status.value if parent_status else None,
        user_email=user.email,
    )

    return SubStatusListResponse(
        items=[SubStatusResponse.model_validate(ss) for ss in substatuses],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


# ── POST /admin/substatuses ────────────────────────────────


@router.post(
    "",
    response_model=SubStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new sub-status",
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "Sub-status with this name already exists for the parent status"},
    },
)
async def create_substatus(
    body: SubStatusCreate,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> SubStatusResponse:
    """Create a new sub-status for the current tenant.

    The sub-status name must be unique within the tenant and parent
    status combination.  An optional display order and default flag
    can be provided.

    If ``is_default`` is ``True``, any existing default sub-status
    for the same parent status will be unset.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    # Check for duplicate name within tenant + parent_status
    existing_stmt = select(SubStatus).where(
        SubStatus.tenant_id == tenant_id,
        SubStatus.parent_status == body.parent_status,
        SubStatus.name == body.name,
    )
    existing_result = await db.execute(existing_stmt)
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A sub-status with name '{body.name}' already exists "
                f"for parent status '{body.parent_status.value}'."
            ),
        )

    # If this is the new default, unset existing defaults
    if body.is_default:
        await _clear_default_substatus(
            db, tenant_id, body.parent_status,
        )

    substatus = SubStatus(
        tenant_id=tenant_id,
        parent_status=body.parent_status,
        name=body.name,
        display_order=body.display_order,
        is_default=body.is_default,
    )
    db.add(substatus)
    await db.flush()
    await db.refresh(substatus)

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.SUB_STATUS_CREATED,
        resource_type="sub_status",
        resource_id=str(substatus.id),
        actor_id=user.id,
        actor_type="user",
        details={
            "parent_status": body.parent_status.value,
            "name": body.name,
            "is_default": body.is_default,
        },
    )

    await db.commit()

    logger.info(
        "admin_substatus_created",
        substatus_id=str(substatus.id),
        substatus_name=body.name,
        parent_status=body.parent_status.value,
        tenant_id=str(tenant_id),
        user_email=user.email,
    )

    return SubStatusResponse.model_validate(substatus)


# ── GET /admin/substatuses/{substatus_id} ───────────────────


@router.get(
    "/{substatus_id}",
    response_model=SubStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single sub-status by ID",
    responses={
        404: {"description": "Sub-status not found"},
    },
)
async def get_substatus(
    substatus_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> SubStatusResponse:
    """Get a single sub-status by its ID.

    Returns 404 if the sub-status does not exist or belongs to a
    different tenant.

    Requires ``cases:read`` scope.
    """
    stmt = select(SubStatus).where(
        SubStatus.id == substatus_id,
        SubStatus.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    substatus = result.scalar_one_or_none()

    if substatus is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sub-status not found.",
        )

    return SubStatusResponse.model_validate(substatus)


# ── PUT /admin/substatuses/{substatus_id} ───────────────────


@router.put(
    "/{substatus_id}",
    response_model=SubStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a sub-status",
    responses={
        404: {"description": "Sub-status not found"},
        409: {"description": "Sub-status with this name already exists for the parent status"},
    },
)
async def update_substatus(
    substatus_id: uuid.UUID,
    body: SubStatusUpdate,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> SubStatusResponse:
    """Update a sub-status's name, display order, default flag, or
    active status.

    All fields are optional -- only provided fields will be updated.

    If ``is_default`` is set to ``True``, any existing default
    sub-status for the same parent status will be unset.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    stmt = select(SubStatus).where(
        SubStatus.id == substatus_id,
        SubStatus.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    substatus = result.scalar_one_or_none()

    if substatus is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sub-status not found.",
        )

    # Check for duplicate name if name is being changed
    if body.name is not None and body.name != substatus.name:
        dup_stmt = select(SubStatus).where(
            SubStatus.tenant_id == tenant_id,
            SubStatus.parent_status == substatus.parent_status,
            SubStatus.name == body.name,
            SubStatus.id != substatus_id,
        )
        dup_result = await db.execute(dup_stmt)
        if dup_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A sub-status with name '{body.name}' already exists "
                    f"for parent status '{substatus.parent_status.value}'."
                ),
            )

    # If setting as new default, unset existing defaults
    if body.is_default is True and not substatus.is_default:
        await _clear_default_substatus(
            db, tenant_id, substatus.parent_status,
        )

    # Track changes for audit
    changes: dict[str, dict] = {}
    update_data = body.model_dump(exclude_none=True)

    for field, new_value in update_data.items():
        old_value = getattr(substatus, field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
            setattr(substatus, field, new_value)

    if changes:
        await db.flush()
        await db.refresh(substatus)

        # Audit trail
        audit_repo = AuditRepository(db)
        await audit_repo.log(
            tenant_id=tenant_id,
            action=AuditAction.SUB_STATUS_UPDATED,
            resource_type="sub_status",
            resource_id=str(substatus.id),
            actor_id=user.id,
            actor_type="user",
            details={"changes": {k: v["new"] for k, v in changes.items()}},
        )

        await db.commit()

    logger.info(
        "admin_substatus_updated",
        substatus_id=str(substatus_id),
        tenant_id=str(tenant_id),
        user_email=user.email,
        changes=list(changes.keys()),
    )

    return SubStatusResponse.model_validate(substatus)


# ── DELETE /admin/substatuses/{substatus_id} ────────────────


@router.delete(
    "/{substatus_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a sub-status (soft delete)",
    responses={
        404: {"description": "Sub-status not found"},
    },
)
async def delete_substatus(
    substatus_id: uuid.UUID,
    user=Security(get_current_user, scopes=["cases:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> None:
    """Deactivate a sub-status (soft delete).

    The sub-status is not physically deleted -- it is marked as
    inactive so that existing report assignments are preserved.
    Inactive sub-statuses are hidden from new assignment dropdowns.

    Requires ``cases:write`` scope (HANDLER, TENANT_ADMIN,
    SYSTEM_ADMIN).
    """
    stmt = select(SubStatus).where(
        SubStatus.id == substatus_id,
        SubStatus.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    substatus = result.scalar_one_or_none()

    if substatus is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sub-status not found.",
        )

    substatus.is_active = False
    await db.flush()

    # Audit trail
    audit_repo = AuditRepository(db)
    await audit_repo.log(
        tenant_id=tenant_id,
        action=AuditAction.SUB_STATUS_DELETED,
        resource_type="sub_status",
        resource_id=str(substatus.id),
        actor_id=user.id,
        actor_type="user",
        details={
            "name": substatus.name,
            "parent_status": substatus.parent_status.value,
        },
    )

    await db.commit()

    logger.info(
        "admin_substatus_deactivated",
        substatus_id=str(substatus_id),
        substatus_name=substatus.name,
        tenant_id=str(tenant_id),
        user_email=user.email,
    )


# ── Helpers ─────────────────────────────────────────────────


async def _clear_default_substatus(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parent_status: ReportStatus,
) -> None:
    """Unset the ``is_default`` flag on all sub-statuses for a given
    tenant and parent status.

    Called before setting a new default to ensure only one default
    exists per parent status.
    """
    stmt = select(SubStatus).where(
        SubStatus.tenant_id == tenant_id,
        SubStatus.parent_status == parent_status,
        SubStatus.is_default.is_(True),
    )
    result = await db.execute(stmt)
    for ss in result.scalars().all():
        ss.is_default = False
    await db.flush()
