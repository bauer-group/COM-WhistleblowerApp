"""Hinweisgebersystem – Pydantic Schema Package.

Re-exports all Pydantic v2 request/response schemas for convenient
imports across the application.

Usage::

    from app.schemas import ReportCreate, ReportResponse, ErrorResponse
    from app.schemas import PaginatedResponse, PaginationParams
"""

from app.schemas.auth import (
    MagicLinkRequest,
    MagicLinkResponse,
    MagicLinkVerify,
    MagicLinkVerifyResponse,
    MailboxLoginRequest,
    MailboxLoginResponse,
    OIDCCallbackRequest,
    OIDCTokenResponse,
    TokenRefreshResponse,
)
from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    HealthCheck,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    TimestampSchema,
    UUIDSchema,
)
from app.schemas.message import (
    MessageCreate,
    MessageCreateHandler,
    MessageListResponse,
    MessageMailboxResponse,
    MessageMarkRead,
    MessageResponse,
)
from app.schemas.report import (
    AttachmentSummary,
    MessageSummary,
    ReportCreate,
    ReportCreateResponse,
    ReportListFilters,
    ReportListResponse,
    ReportMailboxResponse,
    ReportResponse,
    ReportUpdate,
)
from app.schemas.tenant import (
    TenantBranding,
    TenantConfig,
    TenantCreate,
    TenantListResponse,
    TenantPublicInfo,
    TenantResponse,
    TenantSMTPConfig,
    TenantUpdate,
)
from app.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserSummary,
    UserUpdate,
)

__all__ = [
    # ── Common ────────────────────────────────────────────────
    "ErrorDetail",
    "ErrorResponse",
    "HealthCheck",
    "PaginatedResponse",
    "PaginationMeta",
    "PaginationParams",
    "TimestampSchema",
    "UUIDSchema",
    # ── Report ────────────────────────────────────────────────
    "AttachmentSummary",
    "MessageSummary",
    "ReportCreate",
    "ReportCreateResponse",
    "ReportListFilters",
    "ReportListResponse",
    "ReportMailboxResponse",
    "ReportResponse",
    "ReportUpdate",
    # ── Message ───────────────────────────────────────────────
    "MessageCreate",
    "MessageCreateHandler",
    "MessageListResponse",
    "MessageMailboxResponse",
    "MessageMarkRead",
    "MessageResponse",
    # ── User ──────────────────────────────────────────────────
    "UserCreate",
    "UserListResponse",
    "UserResponse",
    "UserSummary",
    "UserUpdate",
    # ── Tenant ────────────────────────────────────────────────
    "TenantBranding",
    "TenantConfig",
    "TenantCreate",
    "TenantListResponse",
    "TenantPublicInfo",
    "TenantResponse",
    "TenantSMTPConfig",
    "TenantUpdate",
    # ── Auth ──────────────────────────────────────────────────
    "MagicLinkRequest",
    "MagicLinkResponse",
    "MagicLinkVerify",
    "MagicLinkVerifyResponse",
    "MailboxLoginRequest",
    "MailboxLoginResponse",
    "OIDCCallbackRequest",
    "OIDCTokenResponse",
    "TokenRefreshResponse",
]
