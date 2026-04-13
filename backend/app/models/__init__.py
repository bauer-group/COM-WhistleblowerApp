"""Hinweisgebersystem – ORM Model Package.

Re-exports all SQLAlchemy ORM models and enums so that they are
registered with ``Base.metadata`` when this package is imported.
Alembic's ``env.py`` imports ``Base`` from ``app.core.database``, and
as long as all models have been imported beforehand (via this package),
``target_metadata`` will reflect the full schema.

Usage::

    # Import all models at once
    from app.models import Report, Message, User, Tenant

    # Import specific enums
    from app.models import ReportStatus, UserRole, Channel
"""

from app.models.attachment import Attachment
from app.models.audit_log import AuditAction, AuditLog
from app.models.category_translation import CategoryTranslation
from app.models.identity_disclosure import DisclosureStatus, IdentityDisclosure
from app.models.label import Label
from app.models.message import Message, SenderType
from app.models.report import (
    Channel,
    LkSGCategory,
    Priority,
    Report,
    ReporterRelationship,
    ReportStatus,
    SupplyChainTier,
    report_labels,
)
from app.models.substatus import SubStatus
from app.models.tenant import Tenant
from app.models.types import PGPString
from app.models.user import User, UserRole

__all__ = [
    # Models
    "Attachment",
    "AuditLog",
    "CategoryTranslation",
    "IdentityDisclosure",
    "Label",
    "Message",
    "Report",
    "SubStatus",
    "Tenant",
    "User",
    # Association tables
    "report_labels",
    # Type decorators
    "PGPString",
    # Enums
    "AuditAction",
    "Channel",
    "DisclosureStatus",
    "LkSGCategory",
    "Priority",
    "ReportStatus",
    "ReporterRelationship",
    "SenderType",
    "SupplyChainTier",
    "UserRole",
]
