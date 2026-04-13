"""Hinweisgebersystem – Backend Application Package.

This package contains the core application modules:
- api/       – FastAPI router modules (v1 endpoints)
- core/      – Configuration, security, encryption, database
- models/    – SQLAlchemy ORM models
- schemas/   – Pydantic request/response schemas
- services/  – Business logic layer
- middleware/ – HTTP middleware (tenant, audit, rate limit, anonymity)
- repositories/ – Database access layer
- tasks/     – Background jobs (deadlines, retention, email)
- scripts/   – CLI scripts (init_db)
"""
