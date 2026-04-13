"""Hinweisgebersystem -- User Business Service.

Orchestrates all user lifecycle operations including:
- **OIDC provisioning**: automatic user creation from Microsoft Entra ID
  claims (email, display name, subject) on first login with default
  role assignment.
- **Role management**: assignment and validation of the 5 RBAC roles
  (system_admin, tenant_admin, handler, reviewer, auditor).
- **Activation / deactivation**: soft-disable users while preserving
  audit trail integrity.
- **Custodian management**: toggle identity disclosure custodian status
  for the 4-eyes principle.
- **Retrieval**: single user by ID/email/OIDC subject, paginated lists
  with filters, handler/custodian listings.
- **Login tracking**: record last login timestamps after OIDC auth.

The service delegates all database access to ``UserRepository`` and
all audit logging to ``AuditRepository``.  Backend users authenticate
exclusively via OIDC (Microsoft Entra ID) — this service does NOT
handle anonymous reporters.

Usage::

    from app.services.user_service import UserService

    service = UserService(session, tenant_id)
    user = await service.provision_from_oidc(email, display_name, oidc_subject)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.repositories.audit_repo import AuditRepository
from app.repositories.user_repo import UserRepository
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.user import UserCreate, UserUpdate

logger = structlog.get_logger(__name__)

# ── Role hierarchy (for validation) ─────────────────────────
# Higher index = higher privilege.  Used to prevent privilege
# escalation (a user cannot assign a role higher than their own).

_ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.AUDITOR: 0,
    UserRole.REVIEWER: 1,
    UserRole.HANDLER: 2,
    UserRole.TENANT_ADMIN: 3,
    UserRole.SYSTEM_ADMIN: 4,
}


class UserService:
    """Business logic for backend user management.

    Parameters
    ----------
    session:
        RLS-scoped async database session (tenant context already set).
    tenant_id:
        UUID of the current tenant (from middleware).
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_repo = UserRepository(session)
        self._audit_repo = AuditRepository(session)

    # ── OIDC Provisioning ────────────────────────────────────

    async def provision_from_oidc(
        self,
        *,
        email: str,
        display_name: str,
        oidc_subject: str,
        default_role: UserRole = UserRole.REVIEWER,
    ) -> tuple[User, bool]:
        """Provision or retrieve a user from OIDC claims.

        On first login the user is created with the given default role.
        On subsequent logins the existing user is returned and the
        last-login timestamp is updated.

        Parameters
        ----------
        email:
            Email address from the OIDC token.
        display_name:
            Human-readable name from the OIDC token.
        oidc_subject:
            The ``sub`` claim from the Entra ID token (globally unique).
        default_role:
            Role assigned to newly provisioned users.  Defaults to
            ``REVIEWER`` (lowest privilege with case access).

        Returns
        -------
        tuple[User, bool]
            The user instance and a boolean indicating whether the user
            was newly created (``True``) or already existed (``False``).

        Raises
        ------
        ValueError
            If the user exists but is deactivated.
        """
        # Try to find by OIDC subject first (most reliable identifier)
        existing = await self._user_repo.get_by_oidc_subject(oidc_subject)

        if existing is not None:
            if not existing.is_active:
                logger.warning(
                    "oidc_login_inactive_user",
                    email=email,
                    oidc_subject=oidc_subject,
                )
                raise ValueError(
                    f"User account for {email} is deactivated. "
                    "Contact your administrator."
                )

            # Update display name if it changed in Entra ID
            if existing.display_name != display_name:
                await self._user_repo.update(
                    existing.id,
                    display_name=display_name,
                )

            # Record login
            await self._user_repo.update_last_login(existing.id)

            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.USER_LOGIN,
                resource_type="user",
                resource_id=str(existing.id),
                actor_id=existing.id,
                actor_type="user",
                details={"email": email},
            )

            logger.info(
                "oidc_user_login",
                email=email,
                user_id=str(existing.id),
            )

            return existing, False

        # New user — create with default role
        user = User(
            tenant_id=self._tenant_id,
            email=email,
            display_name=display_name,
            oidc_subject=oidc_subject,
            role=default_role,
            is_active=True,
            is_custodian=False,
        )
        user = await self._user_repo.create(user)

        # Record login timestamp
        await self._user_repo.update_last_login(user.id)

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_CREATED,
            resource_type="user",
            resource_id=str(user.id),
            actor_type="system",
            details={
                "email": email,
                "role": default_role.value,
                "provisioned_via": "oidc",
            },
        )

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            resource_id=str(user.id),
            actor_id=user.id,
            actor_type="user",
            details={"email": email, "first_login": True},
        )

        logger.info(
            "oidc_user_provisioned",
            email=email,
            role=default_role.value,
            user_id=str(user.id),
        )

        return user, True

    # ── Create (manual) ──────────────────────────────────────

    async def create_user(
        self,
        data: UserCreate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        """Create a new backend user manually (admin action).

        Unlike OIDC provisioning, this is an explicit admin action to
        pre-register a user before their first OIDC login.

        Parameters
        ----------
        data:
            Validated user creation schema.
        actor_id:
            UUID of the admin performing the action (for audit trail).

        Returns
        -------
        User
            The newly created user.

        Raises
        ------
        ValueError
            If a user with the same email or OIDC subject already exists
            within the tenant.
        """
        # Check for duplicate email
        existing_email = await self._user_repo.get_by_email(data.email)
        if existing_email is not None:
            raise ValueError(
                f"A user with email '{data.email}' already exists in this tenant."
            )

        # Check for duplicate OIDC subject
        existing_oidc = await self._user_repo.get_by_oidc_subject(data.oidc_subject)
        if existing_oidc is not None:
            raise ValueError(
                f"A user with OIDC subject '{data.oidc_subject}' already exists."
            )

        user = User(
            tenant_id=self._tenant_id,
            email=data.email,
            display_name=data.display_name,
            oidc_subject=data.oidc_subject,
            role=data.role,
            is_active=True,
            is_custodian=data.is_custodian,
        )
        user = await self._user_repo.create(user)

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_CREATED,
            resource_type="user",
            resource_id=str(user.id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "email": data.email,
                "role": data.role.value,
                "is_custodian": data.is_custodian,
            },
        )

        logger.info(
            "user_created_manually",
            email=data.email,
            role=data.role.value,
            created_by=str(actor_id) if actor_id else "system",
        )

        return user

    # ── Read (single) ────────────────────────────────────────

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Fetch a single user by ID.

        RLS ensures tenant isolation.  Returns ``None`` if not found.
        """
        return await self._user_repo.get_by_id(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        """Fetch a user by email address (tenant-scoped via RLS)."""
        return await self._user_repo.get_by_email(email)

    async def get_user_by_oidc_subject(
        self,
        oidc_subject: str,
    ) -> User | None:
        """Fetch a user by their OIDC subject claim."""
        return await self._user_repo.get_by_oidc_subject(oidc_subject)

    # ── Read (list) ──────────────────────────────────────────

    async def list_users(
        self,
        *,
        pagination: PaginationParams,
        role: UserRole | None = None,
        is_active: bool | None = None,
        is_custodian: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[User], PaginationMeta]:
        """List users with optional filtering and pagination.

        Delegates to the repository with all filter parameters.
        """
        return await self._user_repo.list_paginated(
            pagination=pagination,
            role=role,
            is_active=is_active,
            is_custodian=is_custodian,
            search=search,
        )

    async def list_handlers(self) -> list[User]:
        """List all active users with handler or higher role.

        Used for case assignment dropdowns in the admin UI.
        """
        return await self._user_repo.list_handlers()

    async def list_custodians(self) -> list[User]:
        """List all active identity disclosure custodians.

        Used for the 4-eyes principle custodian selection.
        """
        return await self._user_repo.list_custodians()

    # ── Update ───────────────────────────────────────────────

    async def update_user(
        self,
        user_id: uuid.UUID,
        data: UserUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User | None:
        """Update user fields.

        Handles role changes, activation/deactivation, custodian status,
        and display name updates.  All changes are logged to the audit
        trail.

        Parameters
        ----------
        user_id:
            UUID of the user to update.
        data:
            Validated update schema (only provided fields are applied).
        actor_id:
            UUID of the admin performing the update.

        Returns
        -------
        User | None
            The updated user or ``None`` if not found.
        """
        current = await self._user_repo.get_by_id(user_id)
        if current is None:
            return None

        update_fields: dict[str, Any] = {}
        audit_details: dict[str, Any] = {}

        # Display name
        if data.display_name is not None and data.display_name != current.display_name:
            update_fields["display_name"] = data.display_name
            audit_details["display_name"] = {
                "old": current.display_name,
                "new": data.display_name,
            }

        # Role change
        if data.role is not None and data.role != current.role:
            update_fields["role"] = data.role
            audit_details["role"] = {
                "old": current.role.value,
                "new": data.role.value,
            }

        # Activation / deactivation
        if data.is_active is not None and data.is_active != current.is_active:
            update_fields["is_active"] = data.is_active
            audit_details["is_active"] = {
                "old": current.is_active,
                "new": data.is_active,
            }

        # Custodian status
        if data.is_custodian is not None and data.is_custodian != current.is_custodian:
            update_fields["is_custodian"] = data.is_custodian
            audit_details["is_custodian"] = {
                "old": current.is_custodian,
                "new": data.is_custodian,
            }

        if not update_fields:
            return current

        updated = await self._user_repo.update(user_id, **update_fields)

        if updated is not None:
            # Determine the specific audit action
            if "is_active" in update_fields and not update_fields["is_active"]:
                action = AuditAction.USER_DEACTIVATED
            else:
                action = AuditAction.USER_UPDATED

            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=action,
                resource_type="user",
                resource_id=str(user_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details=audit_details,
            )

            logger.info(
                "user_updated",
                user_id=str(user_id),
                changes=list(update_fields.keys()),
            )

        return updated

    # ── Role Management ──────────────────────────────────────

    async def assign_role(
        self,
        user_id: uuid.UUID,
        role: UserRole,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User | None:
        """Assign a specific RBAC role to a user.

        Convenience method for role-only updates.

        Parameters
        ----------
        user_id:
            UUID of the user to update.
        role:
            The new RBAC role.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        User | None
            The updated user or ``None`` if not found.
        """
        current = await self._user_repo.get_by_id(user_id)
        if current is None:
            return None

        if current.role == role:
            return current

        old_role = current.role
        updated = await self._user_repo.update_role(user_id, role)

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.USER_UPDATED,
                resource_type="user",
                resource_id=str(user_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "role": {
                        "old": old_role.value,
                        "new": role.value,
                    },
                },
            )

            logger.info(
                "user_role_changed",
                user_id=str(user_id),
                old_role=old_role.value,
                new_role=role.value,
            )

        return updated

    def validate_role_assignment(
        self,
        actor_role: UserRole,
        target_role: UserRole,
    ) -> None:
        """Validate that an actor can assign a target role.

        Enforces the privilege hierarchy: a user cannot assign a role
        higher than their own.

        Parameters
        ----------
        actor_role:
            Role of the user performing the assignment.
        target_role:
            Role being assigned.

        Raises
        ------
        ValueError
            If the actor lacks sufficient privileges.
        """
        actor_level = _ROLE_HIERARCHY.get(actor_role, -1)
        target_level = _ROLE_HIERARCHY.get(target_role, -1)

        if target_level > actor_level:
            raise ValueError(
                f"Insufficient privileges: {actor_role.value} cannot assign "
                f"the {target_role.value} role."
            )

    # ── Activation / Deactivation ────────────────────────────

    async def activate_user(
        self,
        user_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User | None:
        """Re-activate a deactivated user.

        Parameters
        ----------
        user_id:
            UUID of the user to activate.
        actor_id:
            UUID of the admin performing the action.

        Returns
        -------
        User | None
            The activated user or ``None`` if not found.
        """
        current = await self._user_repo.get_by_id(user_id)
        if current is None:
            return None

        if current.is_active:
            return current

        activated = await self._user_repo.activate(user_id)

        if activated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.USER_UPDATED,
                resource_type="user",
                resource_id=str(user_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "is_active": {"old": False, "new": True},
                },
            )

            logger.info(
                "user_activated",
                user_id=str(user_id),
            )

        return activated

    async def deactivate_user(
        self,
        user_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User | None:
        """Deactivate a user (soft delete).

        Deactivated users cannot log in via OIDC but their data is
        preserved for audit trail integrity.

        Parameters
        ----------
        user_id:
            UUID of the user to deactivate.
        actor_id:
            UUID of the admin performing the action.

        Returns
        -------
        User | None
            The deactivated user or ``None`` if not found.
        """
        current = await self._user_repo.get_by_id(user_id)
        if current is None:
            return None

        if not current.is_active:
            return current

        deactivated = await self._user_repo.deactivate(user_id)

        if deactivated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.USER_DEACTIVATED,
                resource_type="user",
                resource_id=str(user_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "is_active": {"old": True, "new": False},
                    "email": deactivated.email,
                },
            )

            logger.info(
                "user_deactivated",
                user_id=str(user_id),
                email=deactivated.email,
            )

        return deactivated

    # ── Custodian Management ─────────────────────────────────

    async def set_custodian_status(
        self,
        user_id: uuid.UUID,
        is_custodian: bool,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> User | None:
        """Toggle a user's identity disclosure custodian status.

        Custodians can approve or reject identity disclosure requests
        as part of the 4-eyes principle.

        Parameters
        ----------
        user_id:
            UUID of the user.
        is_custodian:
            Whether the user should be a custodian.
        actor_id:
            UUID of the admin performing the change.

        Returns
        -------
        User | None
            The updated user or ``None`` if not found.
        """
        current = await self._user_repo.get_by_id(user_id)
        if current is None:
            return None

        if current.is_custodian == is_custodian:
            return current

        updated = await self._user_repo.set_custodian(user_id, is_custodian)

        if updated is not None:
            await self._audit_repo.log(
                tenant_id=self._tenant_id,
                action=AuditAction.USER_UPDATED,
                resource_type="user",
                resource_id=str(user_id),
                actor_id=actor_id,
                actor_type="user" if actor_id else "system",
                details={
                    "is_custodian": {
                        "old": not is_custodian,
                        "new": is_custodian,
                    },
                },
            )

            logger.info(
                "user_custodian_status_changed",
                user_id=str(user_id),
                is_custodian=is_custodian,
            )

        return updated

    # ── Login Tracking ───────────────────────────────────────

    async def record_login(
        self,
        user_id: uuid.UUID,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Record a user login event.

        Updates the last-login timestamp and creates an audit log entry.

        Parameters
        ----------
        user_id:
            UUID of the user who logged in.
        ip_address:
            IP address of the login request.
        user_agent:
            HTTP User-Agent header of the login request.
        """
        await self._user_repo.update_last_login(user_id)

        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            resource_id=str(user_id),
            actor_id=user_id,
            actor_type="user",
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def record_logout(
        self,
        user_id: uuid.UUID,
        *,
        ip_address: str | None = None,
    ) -> None:
        """Record a user logout event in the audit trail.

        Parameters
        ----------
        user_id:
            UUID of the user who logged out.
        ip_address:
            IP address of the logout request.
        """
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_LOGOUT,
            resource_type="user",
            resource_id=str(user_id),
            actor_id=user_id,
            actor_type="user",
            ip_address=ip_address,
        )

    # ── Delete (retention) ──────────────────────────────────

    async def delete_user(
        self,
        user_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> bool:
        """Hard-delete a user.

        Prefer ``deactivate_user()`` in most cases.  Hard delete is
        only appropriate during data retention cleanup.

        Parameters
        ----------
        user_id:
            UUID of the user to delete.
        actor_id:
            UUID of the admin performing the deletion.

        Returns
        -------
        bool
            ``True`` if the user was deleted.
        """
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            return False

        # Audit before deletion (data will be gone after)
        await self._audit_repo.log(
            tenant_id=self._tenant_id,
            action=AuditAction.USER_DEACTIVATED,
            resource_type="user",
            resource_id=str(user_id),
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            details={
                "email": user.email,
                "action": "hard_delete",
            },
        )

        return await self._user_repo.delete(user_id)

    # ── Counts ──────────────────────────────────────────────

    async def count_users(
        self,
        *,
        is_active: bool | None = None,
    ) -> int:
        """Count users, optionally filtered by active status."""
        return await self._user_repo.count(is_active=is_active)
