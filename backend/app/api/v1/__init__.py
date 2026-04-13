"""Hinweisgebersystem – API v1 Router Aggregation.

Aggregates all v1 sub-routers into a single ``APIRouter`` instance
that is included by the application factory in ``main.py``.

Each sub-router defines its own prefix and tags so that the OpenAPI
schema is cleanly organised by domain.

Usage::

    from app.api.v1 import router as api_v1_router

    app.include_router(api_v1_router)
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router

router = APIRouter(prefix="/api/v1")

# ── Auth endpoints (magic link, OIDC callback) ──────────────
router.include_router(auth_router)

# ── Reporter endpoints ────────────────────────────────────────
from app.api.v1.reports import router as reports_router

router.include_router(reports_router)

# ── Public LkSG complaints ──────────────────────────────────
from app.api.v1.public_complaints import router as complaints_router

router.include_router(complaints_router)

# ── Admin case management ─────────────────────────────────────
from app.api.v1.admin_cases import router as admin_cases_router

router.include_router(admin_cases_router)

# ── Admin user management ─────────────────────────────────────
from app.api.v1.admin_users import router as admin_users_router

router.include_router(admin_users_router)

# ── Admin tenant management ──────────────────────────────────
from app.api.v1.admin_tenants import router as admin_tenants_router

router.include_router(admin_tenants_router)

# ── Admin categories ─────────────────────────────────────────
from app.api.v1.admin_categories import router as admin_categories_router

router.include_router(admin_categories_router)

# ── Admin labels ─────────────────────────────────────────────
from app.api.v1.admin_labels import router as admin_labels_router

router.include_router(admin_labels_router)

# ── Admin audit log ──────────────────────────────────────────
from app.api.v1.admin_audit import router as admin_audit_router

router.include_router(admin_audit_router)

# ── Admin dashboard & reports ────────────────────────────────
from app.api.v1.admin_dashboard import router as admin_dashboard_router

router.include_router(admin_dashboard_router)

# ── Admin custodian ───────────────────────────────────────────
from app.api.v1.admin_custodian import router as admin_custodian_router

router.include_router(admin_custodian_router)

# ── Admin sub-statuses ───────────────────────────────────────
from app.api.v1.admin_substatuses import router as admin_substatuses_router

router.include_router(admin_substatuses_router)

__all__ = ["router"]
