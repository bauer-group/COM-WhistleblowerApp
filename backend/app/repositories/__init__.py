"""Hinweisgebersystem – Repository Package.

Re-exports all repository classes for convenient imports.  Repositories
encapsulate database access logic and provide a clean interface between
the service layer and the SQLAlchemy ORM models.

Usage::

    from app.repositories import ReportRepository, MessageRepository

    repo = ReportRepository(session)
    report = await repo.get_by_id(report_id)
"""

from app.repositories.audit_repo import AuditRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository

__all__ = [
    "AuditRepository",
    "MessageRepository",
    "ReportRepository",
    "TenantRepository",
    "UserRepository",
]
