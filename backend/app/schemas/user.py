"""Hinweisgebersystem – User Pydantic Schemas.

Request and response schemas for backend user management endpoints.
Users are handlers, admins, and auditors who authenticate via OIDC
(Microsoft Entra ID).

This module does NOT contain reporter-related schemas — reporters are
identified only by case number and passphrase hash and are managed
through the report/auth schemas.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import PaginatedResponse, TimestampSchema, UUIDSchema


# ── User Create ───────────────────────────────────────────────


class UserCreate(BaseModel):
    """Schema for creating a new backend user.

    The ``oidc_subject`` is the ``sub`` claim from the Microsoft
    Entra ID token and uniquely identifies the user across the
    identity provider.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(
        description="User's email address (from OIDC token).",
    )
    display_name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable display name.",
    )
    oidc_subject: str = Field(
        min_length=1,
        max_length=255,
        description="OIDC ``sub`` claim (unique identifier from Entra ID).",
    )
    role: UserRole = Field(
        default=UserRole.REVIEWER,
        description="RBAC role determining access permissions.",
    )
    is_custodian: bool = Field(
        default=False,
        description=(
            "Whether this user can act as identity custodian "
            "(4-eyes principle for identity disclosure)."
        ),
    )


# ── User Update ───────────────────────────────────────────────


class UserUpdate(BaseModel):
    """Schema for updating an existing backend user.

    All fields are optional — only provided fields will be updated.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated display name.",
    )
    role: UserRole | None = Field(
        default=None,
        description="Updated RBAC role.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the user.",
    )
    is_custodian: bool | None = Field(
        default=None,
        description="Update custodian status.",
    )


# ── User Response ─────────────────────────────────────────────


class UserResponse(UUIDSchema, TimestampSchema):
    """Full user response for admin user management views."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    email: str
    display_name: str
    oidc_subject: str
    role: UserRole
    is_active: bool
    is_custodian: bool
    last_login_at: datetime | None = None


# ── User Summary (embedded in other responses) ────────────────


class UserSummary(BaseModel):
    """Minimal user info embedded in case assignment responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    role: UserRole


# ── Paginated User List ───────────────────────────────────────


class UserListResponse(PaginatedResponse[UserResponse]):
    """Paginated list of users for user management."""

    pass
