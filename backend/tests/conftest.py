"""Hinweisgebersystem -- Shared Test Fixtures.

Provides:
- Async test infrastructure (``pytest-asyncio`` with ``auto`` mode).
- Isolated test database session using SQLite async (no external DB needed).
- Pre-built ``Settings`` override with deterministic test values.
- Mock fixtures for OIDC, SMTP (``aiosmtplib``), and MinIO clients.
- Factory fixtures for creating ``User`` and ``Tenant`` instances.
- SQLite type-compilation hooks for PostgreSQL-specific column types
  (JSONB, UUID, ARRAY, BYTEA) so that ``Base.metadata.create_all``
  works on the in-memory test database.

Usage::

    @pytest.mark.asyncio
    async def test_something(db_session, test_settings):
        ...
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.database import Base
from app.models.user import User, UserRole


# ── SQLite ↔ PostgreSQL type compatibility ──────────────────
# Patch the SQLite type compiler to handle PostgreSQL-specific column
# types (JSONB, UUID, ARRAY, BYTEA, TSVECTOR) so that
# ``Base.metadata.create_all()`` works on the in-memory test database.
# Direct monkey-patching of ``SQLiteTypeCompiler`` is the most reliable
# approach in SQLAlchemy 2.0+ where ``@compiles`` hooks for types may
# not intercept the TypeCompiler dispatch path.

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "TEXT"
SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"
SQLiteTypeCompiler.visit_BYTEA = lambda self, type_, **kw: "BLOB"
SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"
SQLiteTypeCompiler.visit_TSVECTOR = lambda self, type_, **kw: "TEXT"

# ── pytest-asyncio configuration ─────────────────────────────
# ``auto`` mode marks all async test functions automatically.
pytestmark = pytest.mark.asyncio


# ── Test Settings ────────────────────────────────────────────


@pytest.fixture()
def test_settings() -> Settings:
    """Return a ``Settings`` instance with deterministic test values.

    Uses in-memory/test defaults so that tests never touch real
    infrastructure (no real DB, SMTP, MinIO, or OIDC connections).
    """
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_hwgs",
        database_admin_url="postgresql+asyncpg://admin:admin@localhost:5432/test_hwgs",
        oidc_issuer="https://login.microsoftonline.com/test-tenant/v2.0",
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        encryption_master_key="a" * 64,  # 64 hex chars -> 32 bytes
        smtp_host="localhost",
        smtp_port=1025,
        smtp_user="test",
        smtp_password="test",
        smtp_from="test@example.com",
        s3_endpoint="localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        s3_bucket="test-attachments",
        s3_secure=False,
        redis_url="redis://localhost:6379/15",
        cors_origins="http://localhost:3000",
        hcaptcha_secret="0x0000000000000000000000000000000000000000",
        hcaptcha_sitekey="10000000-ffff-ffff-ffff-000000000000",
        jwt_secret_key="test-jwt-secret-key-for-unit-tests-only",
        jwt_algorithm="HS256",
        jwt_magic_link_expire_minutes=15,
        app_base_url="https://localhost",
        log_level="debug",
    )


# ── Test Database (SQLite async in-memory) ───────────────────


def _register_pgcrypto_stubs(dbapi_conn: object, _rec: object) -> None:
    """Register mock ``pgp_sym_encrypt`` / ``pgp_sym_decrypt`` on SQLite.

    PostgreSQL pgcrypto functions are used by ``PGPString`` columns.
    In the test environment (SQLite) we replace them with identity
    pass-through functions so that INSERT/SELECT work without error.

    The ``dbapi_conn`` from aiosqlite is an ``AsyncAdapt_aiosqlite_connection``
    whose ``create_function()`` method wraps the async call synchronously.
    """
    import json
    import sqlite3

    dbapi_conn.create_function("pgp_sym_encrypt", 2, lambda data, _key: data)
    dbapi_conn.create_function("pgp_sym_decrypt", 2, lambda data, _key: data)
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    # Register adapter so Python lists are stored as JSON text in SQLite
    # (handles ARRAY(String) columns like ``related_case_numbers``).
    sqlite3.register_adapter(list, json.dumps)


@pytest_asyncio.fixture()
async def async_engine():
    """Create an in-memory SQLite async engine for testing.

    All tables are created fresh for each test, ensuring full isolation.
    Mock pgcrypto functions (``pgp_sym_encrypt``, ``pgp_sym_decrypt``)
    are registered so that ``PGPString`` columns work transparently.
    """
    from sqlalchemy import event as sa_event

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Register pgcrypto stubs on every new connection
    sa_event.listen(engine.sync_engine, "connect", _register_pgcrypto_stubs)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(async_engine) -> AsyncIterator[AsyncSession]:
    """Yield an async database session scoped to a single test.

    Each test gets a clean transaction that is rolled back at the end,
    ensuring no state leaks between tests.
    """
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


# ── Test Tenant & User Fixtures ──────────────────────────────

_TEST_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_TEST_USER_IDS = {
    UserRole.SYSTEM_ADMIN: uuid.UUID("00000000-0000-4000-8000-000000000010"),
    UserRole.TENANT_ADMIN: uuid.UUID("00000000-0000-4000-8000-000000000020"),
    UserRole.HANDLER: uuid.UUID("00000000-0000-4000-8000-000000000030"),
    UserRole.REVIEWER: uuid.UUID("00000000-0000-4000-8000-000000000040"),
    UserRole.AUDITOR: uuid.UUID("00000000-0000-4000-8000-000000000050"),
}


@pytest.fixture()
def test_tenant_id() -> uuid.UUID:
    """Return a deterministic test tenant UUID."""
    return _TEST_TENANT_ID


def _make_user(
    role: UserRole,
    *,
    is_active: bool = True,
    tenant_id: uuid.UUID | None = None,
) -> User:
    """Create a ``User`` ORM instance (not persisted) for testing."""
    tid = tenant_id or _TEST_TENANT_ID
    uid = _TEST_USER_IDS.get(role, uuid.uuid4())
    return User(
        id=uid,
        tenant_id=tid,
        email=f"{role.value}@test.example.com",
        display_name=f"Test {role.value.replace('_', ' ').title()}",
        oidc_subject=f"oidc-sub-{role.value}",
        role=role,
        is_active=is_active,
        is_custodian=role in (UserRole.TENANT_ADMIN, UserRole.SYSTEM_ADMIN),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture()
def make_user():
    """Factory fixture to create ``User`` instances with a given role.

    Usage::

        def test_something(make_user):
            admin = make_user(UserRole.SYSTEM_ADMIN)
            handler = make_user(UserRole.HANDLER, is_active=False)
    """
    return _make_user


@pytest.fixture()
def all_role_users(make_user):
    """Return a dict mapping every ``UserRole`` to a ``User`` instance."""
    return {role: make_user(role) for role in UserRole}


# ── Mock OIDC ────────────────────────────────────────────────


@pytest.fixture()
def mock_oidc_signing_key():
    """Mock the OIDC JWKS key retrieval so tests never hit Entra ID.

    Returns an ``AsyncMock`` that the test can configure with a
    specific return value.
    """
    with patch("app.core.oidc.get_signing_key", new_callable=AsyncMock) as m:
        m.return_value = None  # Default: key not found
        yield m


# ── Mock SMTP ────────────────────────────────────────────────


@pytest.fixture()
def mock_smtp():
    """Mock ``aiosmtplib.SMTP`` to prevent real email sends in tests.

    Returns a ``MagicMock`` whose ``connect``, ``send_message``, and
    ``quit`` are all ``AsyncMock``s.
    """
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.send_message = AsyncMock()
    mock.quit = AsyncMock()

    with patch("aiosmtplib.SMTP", return_value=mock) as _:
        yield mock


# ── Mock MinIO ───────────────────────────────────────────────


@pytest.fixture()
def mock_minio():
    """Mock the ``minio.Minio`` client to prevent real S3 calls.

    Provides mocked ``put_object``, ``get_object``, and
    ``remove_object`` methods.
    """
    mock = MagicMock()
    mock.put_object = MagicMock(return_value=None)
    mock.get_object = MagicMock()
    mock.remove_object = MagicMock(return_value=None)
    mock.bucket_exists = MagicMock(return_value=True)
    mock.make_bucket = MagicMock(return_value=None)

    with patch("minio.Minio", return_value=mock) as _:
        yield mock
