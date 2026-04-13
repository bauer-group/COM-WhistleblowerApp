"""Hinweisgebersystem -- Database Initialisation & Seed Script.

Sets up the initial database state required for the system to operate:

1. **Verify pgcrypto extension**: Ensures the ``pgcrypto`` extension is
   available and loaded in the database (required for field-level
   encryption via ``pgp_sym_encrypt`` / ``pgp_sym_decrypt``).
2. **Create system admin tenant**: Seeds the first tenant (slug:
   ``system``) with a generated Data Encryption Key (DEK) encrypted
   via envelope encryption with the master key.
3. **Create system admin user**: Seeds the first ``system_admin`` user
   using environment variables ``INIT_ADMIN_EMAIL``,
   ``INIT_ADMIN_DISPLAY_NAME``, and ``INIT_ADMIN_OIDC_SUBJECT``.
4. **Ensure MinIO bucket**: Verifies (or creates) the default
   attachments bucket in MinIO.

The script is idempotent -- running it multiple times will not
duplicate data.  Existing tenants and users are detected by slug
and OIDC subject respectively.

Usage::

    docker compose exec api python -m app.scripts.init_db

Environment variables (in addition to standard app config):

    INIT_ADMIN_EMAIL          -- Email for the initial system admin
                                 (default: admin@example.com)
    INIT_ADMIN_DISPLAY_NAME   -- Display name for the initial admin
                                 (default: System Administrator)
    INIT_ADMIN_OIDC_SUBJECT   -- OIDC sub claim for the initial admin
                                 (default: init-system-admin)
"""

from __future__ import annotations

import asyncio
import os
import sys

import structlog

logger = structlog.get_logger(__name__)


# ── pgcrypto verification ────────────────────────────────────


async def verify_pgcrypto(session) -> bool:
    """Verify that the pgcrypto extension is available.

    Executes a test call to ``gen_random_uuid()`` (provided by pgcrypto)
    to confirm the extension is loaded.

    Parameters
    ----------
    session:
        Async database session.

    Returns
    -------
    bool
        ``True`` if pgcrypto is available, ``False`` otherwise.
    """
    from sqlalchemy import text

    try:
        result = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'")
        )
        row = result.scalar_one_or_none()
        if row is not None:
            logger.info("pgcrypto_verified", extension=row)
            return True

        logger.error(
            "pgcrypto_missing",
            hint="Run Alembic migrations first: alembic upgrade head",
        )
        return False
    except Exception as exc:
        logger.error("pgcrypto_check_failed", error=str(exc))
        return False


# ── System admin tenant ──────────────────────────────────────


async def ensure_system_tenant(session) -> object:
    """Create or retrieve the system admin tenant.

    The system tenant (slug: ``system``) is the root tenant used for
    cross-tenant system administration.  If it already exists, the
    existing tenant is returned.

    Parameters
    ----------
    session:
        Async database session.

    Returns
    -------
    Tenant
        The system admin tenant instance.
    """
    from app.core.config import get_settings
    from app.core.encryption import encrypt_dek, generate_tenant_dek
    from app.models.tenant import Tenant
    from app.repositories.tenant_repo import TenantRepository
    from app.schemas.tenant import TenantConfig, TenantCreate
    from app.services.tenant_service import TenantService

    settings = get_settings()
    tenant_repo = TenantRepository(session)

    # Check if system tenant already exists
    existing = await tenant_repo.get_by_slug("system")
    if existing is not None:
        logger.info(
            "system_tenant_exists",
            tenant_id=str(existing.id),
            slug=existing.slug,
        )
        return existing

    # Generate and encrypt a DEK for the system tenant
    raw_dek = generate_tenant_dek()
    encrypted_dek = encrypt_dek(raw_dek, settings.encryption_master_key)
    dek_ciphertext = encrypted_dek.hex()

    # Create via TenantService to get default categories seeded
    tenant_service = TenantService(session)
    data = TenantCreate(
        slug="system",
        name="System Administration",
        config=TenantConfig(
            languages=["de", "en"],
            default_language="de",
        ),
    )
    tenant = await tenant_service.create_tenant(
        data,
        dek_ciphertext=dek_ciphertext,
    )

    logger.info(
        "system_tenant_created",
        tenant_id=str(tenant.id),
        slug=tenant.slug,
    )
    return tenant


# ── System admin user ────────────────────────────────────────


async def ensure_system_admin_user(session, tenant_id) -> object:
    """Create or retrieve the initial system admin user.

    User details are read from environment variables:
    - ``INIT_ADMIN_EMAIL`` (default: ``admin@example.com``)
    - ``INIT_ADMIN_DISPLAY_NAME`` (default: ``System Administrator``)
    - ``INIT_ADMIN_OIDC_SUBJECT`` (default: ``init-system-admin``)

    The user is created with role ``system_admin`` in the system
    tenant.  If a user with the same OIDC subject already exists,
    the existing user is returned.

    Parameters
    ----------
    session:
        Async database session.
    tenant_id:
        UUID of the system admin tenant.

    Returns
    -------
    User
        The system admin user instance.
    """
    from app.models.user import User, UserRole
    from app.repositories.user_repo import UserRepository

    admin_email = os.environ.get("INIT_ADMIN_EMAIL", "admin@example.com")
    admin_display_name = os.environ.get(
        "INIT_ADMIN_DISPLAY_NAME", "System Administrator"
    )
    admin_oidc_subject = os.environ.get(
        "INIT_ADMIN_OIDC_SUBJECT", "init-system-admin"
    )

    user_repo = UserRepository(session)

    # Check if admin user already exists by OIDC subject
    existing = await user_repo.get_by_oidc_subject(admin_oidc_subject)
    if existing is not None:
        logger.info(
            "system_admin_user_exists",
            user_id=str(existing.id),
            email=existing.email,
        )
        return existing

    # Create system admin user
    user = User(
        tenant_id=tenant_id,
        email=admin_email,
        display_name=admin_display_name,
        oidc_subject=admin_oidc_subject,
        role=UserRole.SYSTEM_ADMIN,
        is_active=True,
        is_custodian=False,
    )
    user = await user_repo.create(user)

    logger.info(
        "system_admin_user_created",
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
    )
    return user


# ── MinIO bucket ─────────────────────────────────────────────


async def ensure_minio_bucket() -> bool:
    """Ensure the default MinIO attachments bucket exists.

    Initialises the storage client and creates the bucket if it does
    not already exist.

    Returns
    -------
    bool
        ``True`` if the bucket is available, ``False`` on error.
    """
    from app.core.storage import init_storage

    try:
        storage = await init_storage()
        logger.info(
            "minio_bucket_ensured",
            bucket=storage.default_bucket,
        )
        return True
    except Exception as exc:
        logger.error(
            "minio_bucket_failed",
            error=str(exc),
            hint="Ensure MinIO is running and credentials are correct.",
        )
        return False


# ── Main entry point ─────────────────────────────────────────


async def main() -> None:
    """Run the database initialisation sequence.

    Steps:
    1. Initialise the async database engine.
    2. Verify pgcrypto extension is available.
    3. Create or retrieve the system admin tenant.
    4. Create or retrieve the system admin user.
    5. Ensure MinIO bucket exists.
    6. Dispose of the engine and report results.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    settings = get_settings()

    logger.info("init_db_started")

    # ── 1. Create async engine (using admin URL for init) ────
    #
    # We use DATABASE_ADMIN_URL (superuser) instead of DATABASE_URL
    # (app_user) because the init script may need to verify
    # extensions and the app_user RLS context is not yet set up.
    engine = create_async_engine(
        settings.database_admin_url,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    errors: list[str] = []

    try:
        async with session_factory() as session:
            # ── 2. Verify pgcrypto ───────────────────────────
            pgcrypto_ok = await verify_pgcrypto(session)
            if not pgcrypto_ok:
                errors.append("pgcrypto extension not available")
                logger.error(
                    "init_db_abort",
                    reason="pgcrypto is required for field-level encryption",
                )
                return

            # ── 3. Create system tenant ──────────────────────
            try:
                tenant = await ensure_system_tenant(session)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                errors.append(f"Failed to create system tenant: {exc}")
                logger.error("system_tenant_failed", error=str(exc))
                return

        # ── 4. Create system admin user ──────────────────────
        #
        # Use a new session with RLS context set for the system
        # tenant so that the user is created in the correct
        # tenant scope.
        async with session_factory() as session:
            try:
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant.id)},
                )
                user = await ensure_system_admin_user(session, tenant.id)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                errors.append(f"Failed to create system admin user: {exc}")
                logger.error("system_admin_user_failed", error=str(exc))

        # ── 5. Ensure MinIO bucket ───────────────────────────
        minio_ok = await ensure_minio_bucket()
        if not minio_ok:
            errors.append("MinIO bucket setup failed")

    finally:
        await engine.dispose()
        logger.info("database_engine_disposed")

    # ── Report results ───────────────────────────────────────
    if errors:
        logger.warning(
            "init_db_completed_with_errors",
            errors=errors,
        )
        sys.exit(1)
    else:
        logger.info("init_db_completed_successfully")


if __name__ == "__main__":
    asyncio.run(main())
