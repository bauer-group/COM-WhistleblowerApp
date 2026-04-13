"""Hinweisgebersystem – Admin User Management API Endpoints.

Provides:
- **GET /admin/users** — Paginated user list with filters (role,
  active status, custodian status, search).
- **POST /admin/users** — Create a new backend user with role
  assignment (pre-register before first OIDC login).
- **GET /admin/users/{user_id}** — Get a single user's full detail.
- **PATCH /admin/users/{user_id}** — Update user role, display name,
  activation status, or custodian status.
- **DELETE /admin/users/{user_id}/totp** — Admin reset of a user's
  TOTP 2FA (clears all TOTP fields).
- **POST /admin/users/{user_id}/pgp-key** — Upload a PGP public key
  for encrypted email notifications.
- **DELETE /admin/users/{user_id}/pgp-key** — Remove a user's PGP
  public key from the system.

All endpoints require OIDC-authenticated admin users with appropriate
scopes.  Tenant isolation is enforced via Row-Level Security (RLS).

Usage::

    from app.api.v1.admin_users import router as admin_users_router
    api_v1_router.include_router(admin_users_router)
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
from app.models.user import UserRole
from app.schemas.common import PaginationParams
from app.schemas.pgp import PGPKeyDeleteResponse, PGPKeyResponse, PGPKeyUpload
from app.schemas.totp import TOTPAdminResetResponse
from app.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.services.pgp_service import (
    PGPError,
    PGPKeyImportError,
    get_pgp_service,
)
from app.services.user_service import UserService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


# ── GET /admin/users ─────────────────────────────────────────


@router.get(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List users with filters and pagination",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def list_users(
    user=Security(get_current_user, scopes=["users:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    # ── Pagination ───────────────────────────────────────────
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)."
    ),
    # ── Filters ──────────────────────────────────────────────
    role: UserRole | None = Query(
        default=None, description="Filter by RBAC role."
    ),
    is_active: bool | None = Query(
        default=None, description="Filter by active/inactive status."
    ),
    is_custodian: bool | None = Query(
        default=None, description="Filter by custodian capability."
    ),
    search: str | None = Query(
        default=None,
        max_length=500,
        description="Search on email and display name (case-insensitive).",
    ),
) -> UserListResponse:
    """List all backend users with optional filtering and pagination.

    Supports filtering by role, active status, custodian status, and
    free-text search on email / display name.

    Requires ``users:read`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    pagination = PaginationParams(page=page, page_size=page_size)
    user_service = UserService(db, tenant_id)

    users, meta = await user_service.list_users(
        pagination=pagination,
        role=role,
        is_active=is_active,
        is_custodian=is_custodian,
        search=search,
    )

    items = [UserResponse.model_validate(u) for u in users]

    logger.info(
        "admin_users_listed",
        user_email=user.email,
        total=meta.total,
        page=page,
    )

    return UserListResponse(items=items, pagination=meta)


# ── POST /admin/users ────────────────────────────────────────


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new backend user with role assignment",
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "User with this email or OIDC subject already exists"},
    },
)
async def create_user(
    body: UserCreate,
    user=Security(get_current_user, scopes=["users:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> UserResponse:
    """Create a new backend user (pre-register before first OIDC login).

    The user will be created with the specified OIDC subject claim so
    that on their first OIDC login they are automatically matched to
    this pre-registered account with the assigned role.

    Role assignment is validated against the privilege hierarchy — the
    creating admin cannot assign a role higher than their own.

    Requires ``users:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    user_service = UserService(db, tenant_id)

    # Validate privilege hierarchy
    try:
        user_service.validate_role_assignment(user.role, body.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    try:
        new_user = await user_service.create_user(
            body,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    logger.info(
        "admin_user_created",
        new_user_email=new_user.email,
        new_user_role=new_user.role.value,
        created_by=user.email,
    )

    return UserResponse.model_validate(new_user)


# ── GET /admin/users/{user_id} ──────────────────────────────


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single user's detail",
    responses={
        404: {"description": "User not found"},
    },
)
async def get_user(
    user_id: uuid.UUID,
    user=Security(get_current_user, scopes=["users:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> UserResponse:
    """Get a single backend user by ID.

    Returns the full user record including role, active status,
    custodian capability, and timestamps.  Tenant isolation is
    enforced via RLS.

    Requires ``users:read`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    user_service = UserService(db, tenant_id)
    found = await user_service.get_user_by_id(user_id)

    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    logger.info(
        "admin_user_viewed",
        viewed_user_id=str(user_id),
        user_email=user.email,
    )

    return UserResponse.model_validate(found)


# ── PATCH /admin/users/{user_id} ────────────────────────────


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user role, status, or custodian capability",
    responses={
        403: {"description": "Insufficient permissions or privilege escalation"},
        404: {"description": "User not found"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    user=Security(get_current_user, scopes=["users:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> UserResponse:
    """Update a backend user's role, display name, activation status,
    or custodian capability.

    All fields are optional — only provided fields will be updated.
    Role changes are validated against the privilege hierarchy to
    prevent escalation attacks.

    Requires ``users:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    user_service = UserService(db, tenant_id)

    # Validate role assignment if a role change is requested
    if body.role is not None:
        try:
            user_service.validate_role_assignment(user.role, body.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )

    updated = await user_service.update_user(
        user_id,
        body,
        actor_id=user.id,
    )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    logger.info(
        "admin_user_updated",
        updated_user_id=str(user_id),
        user_email=user.email,
        changes={
            k: v
            for k, v in body.model_dump(exclude_none=True).items()
            if v is not None
        },
    )

    return UserResponse.model_validate(updated)


# ── DELETE /admin/users/{user_id}/totp ───────────────────────


@router.delete(
    "/{user_id}/totp",
    response_model=TOTPAdminResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin reset of a user's TOTP 2FA",
    responses={
        403: {"description": "Insufficient permissions"},
        404: {"description": "User not found"},
    },
)
async def reset_user_totp(
    user_id: uuid.UUID,
    user=Security(get_current_user, scopes=["users:write"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> TOTPAdminResetResponse:
    """Admin-reset a user's TOTP 2FA.

    Clears all TOTP fields (secret, backup codes, timestamps, enabled
    flag) so the user can re-enroll.  This is a privileged operation
    for cases where the user has lost their authenticator device and
    all backup codes.

    Requires ``users:write`` scope (TENANT_ADMIN, SYSTEM_ADMIN).

    An audit log entry is created for the TOTP_RESET event.
    """
    from app.models.user import User  # noqa: PLC0415

    # Look up the target user within the tenant (RLS enforced).
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Clear all TOTP fields.
    target_user.totp_secret = None
    target_user.totp_enabled = False
    target_user.totp_verified_at = None
    target_user.totp_last_used_at = None
    target_user.totp_backup_codes_hash = None
    await db.commit()

    # Write audit log entry.
    from app.models.audit_log import AuditAction, AuditLog  # noqa: PLC0415

    audit_entry = AuditLog(
        tenant_id=tenant_id,
        action=AuditAction.TOTP_RESET,
        actor_id=user.id,
        actor_type="user",
        resource_type="user",
        resource_id=str(user_id),
        details={
            "event": "totp_reset",
            "reset_by": str(user.id),
            "target_email": target_user.email,
        },
    )
    db.add(audit_entry)
    await db.commit()

    logger.info(
        "admin_totp_reset",
        target_user_id=str(user_id),
        target_email=target_user.email,
        reset_by=user.email,
    )

    return TOTPAdminResetResponse()


# ── POST /admin/users/{user_id}/pgp-key ─────────────────────


@router.post(
    "/{user_id}/pgp-key",
    response_model=PGPKeyResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a PGP public key for encrypted email notifications",
    responses={
        400: {"description": "Invalid PGP key"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "User not found"},
    },
)
async def upload_pgp_key(
    user_id: uuid.UUID,
    body: PGPKeyUpload,
    user=Security(get_current_user, scopes=["pgp:manage"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> PGPKeyResponse:
    """Upload an ASCII-armored PGP public key for a user.

    The key is validated, imported into the server's GPG keyring, and
    its fingerprint and expiry are stored on the user record.  Once
    uploaded, all email notifications sent to this user will be
    PGP-encrypted.

    If the user already has a PGP key, it is replaced with the new one.

    Requires ``pgp:manage`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    from app.models.user import User  # noqa: PLC0415

    # Look up the target user within the tenant (RLS enforced).
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Import and validate the PGP key.
    pgp_service = get_pgp_service()

    try:
        key_info = pgp_service.import_key(body.public_key)
    except PGPKeyImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # If the user already had a key, delete the old one from the keyring.
    if target_user.pgp_fingerprint and target_user.pgp_fingerprint != key_info.fingerprint:
        try:
            pgp_service.delete_key(target_user.pgp_fingerprint)
        except PGPError:
            pass  # Old key may already be gone; safe to ignore.

    # Update user record with PGP key metadata.
    target_user.pgp_public_key = body.public_key
    target_user.pgp_fingerprint = key_info.fingerprint
    target_user.pgp_key_expires_at = key_info.expires_at
    await db.commit()

    # Write audit log entry.
    from app.models.audit_log import AuditAction, AuditLog  # noqa: PLC0415

    audit_entry = AuditLog(
        tenant_id=tenant_id,
        action=AuditAction.PGP_KEY_UPLOADED,
        actor_id=user.id,
        actor_type="user",
        resource_type="user",
        resource_id=str(user_id),
        details={
            "event": "pgp_key_uploaded",
            "uploaded_by": str(user.id),
            "target_email": target_user.email,
            "fingerprint": key_info.fingerprint,
            "expires_at": str(key_info.expires_at) if key_info.expires_at else None,
        },
    )
    db.add(audit_entry)
    await db.commit()

    logger.info(
        "admin_pgp_key_uploaded",
        target_user_id=str(user_id),
        target_email=target_user.email,
        fingerprint=key_info.fingerprint,
        uploaded_by=user.email,
    )

    return PGPKeyResponse(
        fingerprint=key_info.fingerprint,
        expires_at=key_info.expires_at,
        user_ids=key_info.user_ids,
    )


# ── DELETE /admin/users/{user_id}/pgp-key ────────────────────


@router.delete(
    "/{user_id}/pgp-key",
    response_model=PGPKeyDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a user's PGP public key",
    responses={
        403: {"description": "Insufficient permissions"},
        404: {"description": "User not found or no PGP key configured"},
    },
)
async def delete_pgp_key(
    user_id: uuid.UUID,
    user=Security(get_current_user, scopes=["pgp:manage"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> PGPKeyDeleteResponse:
    """Remove a user's PGP public key from the system.

    Deletes the key from both the GPG keyring and the user record.
    After deletion, email notifications to this user will be sent
    unencrypted.

    Requires ``pgp:manage`` scope (TENANT_ADMIN, SYSTEM_ADMIN).
    """
    from app.models.user import User  # noqa: PLC0415

    # Look up the target user within the tenant (RLS enforced).
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if not target_user.pgp_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No PGP key configured for this user.",
        )

    old_fingerprint = target_user.pgp_fingerprint

    # Delete the key from the GPG keyring.
    pgp_service = get_pgp_service()
    try:
        pgp_service.delete_key(old_fingerprint)
    except PGPError:
        pass  # Key may already be gone from keyring; safe to proceed.

    # Clear PGP fields on the user record.
    target_user.pgp_public_key = None
    target_user.pgp_fingerprint = None
    target_user.pgp_key_expires_at = None
    await db.commit()

    # Write audit log entry.
    from app.models.audit_log import AuditAction, AuditLog  # noqa: PLC0415

    audit_entry = AuditLog(
        tenant_id=tenant_id,
        action=AuditAction.PGP_KEY_DELETED,
        actor_id=user.id,
        actor_type="user",
        resource_type="user",
        resource_id=str(user_id),
        details={
            "event": "pgp_key_deleted",
            "deleted_by": str(user.id),
            "target_email": target_user.email,
            "fingerprint": old_fingerprint,
        },
    )
    db.add(audit_entry)
    await db.commit()

    logger.info(
        "admin_pgp_key_deleted",
        target_user_id=str(user_id),
        target_email=target_user.email,
        old_fingerprint=old_fingerprint,
        deleted_by=user.email,
    )

    return PGPKeyDeleteResponse()
