"""Hinweisgebersystem – Admin Dashboard & Reports API Endpoints.

Provides:
- **GET /admin/dashboard/stats** — KPI dashboard with case counts
  by status, channel, and priority; average resolution time; overdue
  count; and trend data for the last 12 months.
- **GET /admin/reports/lksg-effectiveness** — LkSG effectiveness
  report with complaint resolution metrics and category breakdown.
- **GET /admin/reports/lksg-annual** — Annual report data for LkSG
  compliance documentation.

All endpoints require OIDC-authenticated admin users with the
``dashboard:read`` scope.  Tenant isolation is enforced via Row-Level
Security (RLS).

Usage::

    from app.api.v1.admin_dashboard import router as admin_dashboard_router
    api_v1_router.include_router(admin_dashboard_router)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.middleware.tenant_resolver import get_current_tenant, get_tenant_db
from app.models.report import (
    Channel,
    Priority,
    Report,
    ReportStatus,
)
from app.services.report_service import ReportService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["admin-dashboard"])


# -- Response schemas ---------------------------------------------------------


class StatusCount(BaseModel):
    """Count of cases for a specific status."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Case status value.")
    count: int = Field(description="Number of cases with this status.")


class ChannelCount(BaseModel):
    """Count of cases for a specific reporting channel."""

    model_config = ConfigDict(frozen=True)

    channel: str = Field(description="Reporting channel (hinschg or lksg).")
    count: int = Field(description="Number of cases from this channel.")


class PriorityCount(BaseModel):
    """Count of cases for a specific priority level."""

    model_config = ConfigDict(frozen=True)

    priority: str = Field(description="Priority level.")
    count: int = Field(description="Number of cases with this priority.")


class MonthlyTrend(BaseModel):
    """Monthly case count for trend data."""

    model_config = ConfigDict(frozen=True)

    month: str = Field(
        description="Month in YYYY-MM format.",
        examples=["2026-03"],
    )
    count: int = Field(description="Number of cases created in this month.")


class DashboardStatsResponse(BaseModel):
    """KPI dashboard statistics response."""

    model_config = ConfigDict(frozen=True)

    total_cases: int = Field(description="Total number of cases.")
    by_status: list[StatusCount] = Field(
        description="Case counts grouped by status."
    )
    by_channel: list[ChannelCount] = Field(
        description="Case counts grouped by reporting channel."
    )
    by_priority: list[PriorityCount] = Field(
        description="Case counts grouped by priority level."
    )
    overdue_count: int = Field(
        description="Number of cases with overdue deadlines."
    )
    avg_resolution_days: float | None = Field(
        default=None,
        description=(
            "Average number of days from case creation to closure. "
            "None if no cases have been closed."
        ),
    )
    monthly_trend: list[MonthlyTrend] = Field(
        description="Case creation trend for the last 12 months."
    )


class LkSGCategoryCount(BaseModel):
    """Count of LkSG complaints by category."""

    model_config = ConfigDict(frozen=True)

    category: str = Field(description="LkSG complaint category.")
    count: int = Field(description="Number of complaints in this category.")


class LkSGEffectivenessResponse(BaseModel):
    """LkSG effectiveness report response.

    Provides metrics required by LkSG Section 8 para. 1 for evaluating
    the effectiveness of the complaints procedure.
    """

    model_config = ConfigDict(frozen=True)

    total_complaints: int = Field(
        description="Total number of LkSG complaints received."
    )
    resolved_complaints: int = Field(
        description="Number of LkSG complaints resolved (abgeschlossen)."
    )
    pending_complaints: int = Field(
        description="Number of LkSG complaints still in progress."
    )
    avg_resolution_days: float | None = Field(
        default=None,
        description=(
            "Average days to resolve LkSG complaints. "
            "None if no complaints have been resolved."
        ),
    )
    by_category: list[LkSGCategoryCount] = Field(
        description="Complaint counts grouped by LkSG category."
    )
    overdue_count: int = Field(
        description="Number of LkSG complaints with overdue deadlines."
    )
    resolution_rate: float = Field(
        description="Percentage of complaints resolved (0.0 to 100.0)."
    )


class LkSGAnnualReportResponse(BaseModel):
    """Annual report data for LkSG compliance documentation.

    Provides the data points required for the annual effectiveness
    report mandated by LkSG Section 10 para. 2.
    """

    model_config = ConfigDict(frozen=True)

    year: int = Field(description="Reporting year.")
    total_complaints: int = Field(
        description="Total LkSG complaints received in the reporting year."
    )
    resolved_complaints: int = Field(
        description="LkSG complaints resolved in the reporting year."
    )
    pending_complaints: int = Field(
        description="LkSG complaints still pending at year end."
    )
    avg_resolution_days: float | None = Field(
        default=None,
        description="Average days to resolve complaints in the reporting year.",
    )
    by_category: list[LkSGCategoryCount] = Field(
        description="Complaint counts by LkSG category for the year."
    )
    by_status: list[StatusCount] = Field(
        description="Complaint counts by status at year end."
    )
    resolution_rate: float = Field(
        description="Percentage of complaints resolved (0.0 to 100.0)."
    )
    measures_taken: int = Field(
        default=0,
        description=(
            "Number of complaints where remedial measures were documented. "
            "Derived from cases that progressed to rueckmeldung or abgeschlossen."
        ),
    )


# -- Helpers ------------------------------------------------------------------


async def _count_by_column(
    db: AsyncSession,
    column: Any,
    *,
    extra_filters: list | None = None,
) -> list[tuple[str, int]]:
    """Count reports grouped by a given column.

    Parameters
    ----------
    db:
        Async database session.
    column:
        The SQLAlchemy column to group by.
    extra_filters:
        Optional list of additional WHERE clauses.

    Returns
    -------
    list[tuple[str, int]]
        Tuples of (column_value, count).
    """
    stmt = select(column, func.count()).group_by(column)
    if extra_filters:
        for f in extra_filters:
            stmt = stmt.where(f)
    result = await db.execute(stmt)
    return [(row[0].value if hasattr(row[0], "value") else str(row[0]), row[1]) for row in result.all()]


async def _avg_resolution_days(
    db: AsyncSession,
    *,
    extra_filters: list | None = None,
) -> float | None:
    """Calculate average resolution time in days for closed cases.

    Only considers cases with status ``abgeschlossen``.

    Returns
    -------
    float | None
        Average days, or ``None`` if no closed cases exist.
    """
    stmt = select(
        func.avg(
            func.extract("epoch", Report.updated_at - Report.created_at)
            / 86400.0
        )
    ).where(Report.status == ReportStatus.ABGESCHLOSSEN)

    if extra_filters:
        for f in extra_filters:
            stmt = stmt.where(f)

    result = await db.execute(stmt)
    avg_val = result.scalar_one_or_none()
    if avg_val is None:
        return None
    return round(float(avg_val), 1)


async def _monthly_trend(
    db: AsyncSession,
    months: int = 12,
) -> list[MonthlyTrend]:
    """Get monthly case creation counts for the last N months.

    Returns
    -------
    list[MonthlyTrend]
        Monthly counts ordered chronologically.
    """
    cutoff = datetime.now(UTC) - timedelta(days=months * 30)

    stmt = (
        select(
            func.to_char(Report.created_at, "YYYY-MM").label("month"),
            func.count().label("count"),
        )
        .where(Report.created_at >= cutoff)
        .group_by(func.to_char(Report.created_at, "YYYY-MM"))
        .order_by(func.to_char(Report.created_at, "YYYY-MM"))
    )

    result = await db.execute(stmt)
    return [
        MonthlyTrend(month=row.month, count=row.count)
        for row in result.all()
    ]


# -- GET /admin/dashboard/stats -----------------------------------------------


@router.get(
    "/admin/dashboard/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get KPI dashboard statistics",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def get_dashboard_stats(
    user=Security(get_current_user, scopes=["dashboard:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> DashboardStatsResponse:
    """Return KPI statistics for the admin dashboard.

    Provides a comprehensive overview of case metrics including:
    - Total case count and breakdown by status, channel, priority
    - Number of overdue cases (confirmation or feedback deadline passed)
    - Average resolution time for closed cases
    - Monthly trend data for the last 12 months

    Requires ``dashboard:read`` scope (HANDLER, REVIEWER, AUDITOR,
    TENANT_ADMIN, SYSTEM_ADMIN).
    """
    report_service = ReportService(db, tenant_id)

    # Get basic KPI stats from service layer
    kpi = await report_service.get_kpi_statistics()

    # Build status counts
    by_status = [
        StatusCount(status=s, count=c) for s, c in kpi["by_status"].items()
    ]

    # Count by channel
    channel_data = await _count_by_column(db, Report.channel)
    by_channel = [
        ChannelCount(channel=ch, count=c) for ch, c in channel_data
    ]

    # Count by priority
    priority_data = await _count_by_column(db, Report.priority)
    by_priority = [
        PriorityCount(priority=p, count=c) for p, c in priority_data
    ]

    # Average resolution time
    avg_days = await _avg_resolution_days(db)

    # Monthly trend
    trend = await _monthly_trend(db)

    logger.info(
        "admin_dashboard_stats_viewed",
        user_email=user.email,
        total_cases=kpi["total"],
    )

    return DashboardStatsResponse(
        total_cases=kpi["total"],
        by_status=by_status,
        by_channel=by_channel,
        by_priority=by_priority,
        overdue_count=kpi["overdue_count"],
        avg_resolution_days=avg_days,
        monthly_trend=trend,
    )


# -- GET /admin/reports/lksg-effectiveness ------------------------------------


@router.get(
    "/admin/reports/lksg-effectiveness",
    response_model=LkSGEffectivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get LkSG effectiveness report",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def get_lksg_effectiveness(
    user=Security(get_current_user, scopes=["dashboard:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
) -> LkSGEffectivenessResponse:
    """Return LkSG effectiveness report data.

    Provides metrics required by LkSG Section 8 para. 1 for evaluating
    the effectiveness of the complaints procedure, including:
    - Total, resolved, and pending complaint counts
    - Average resolution time
    - Breakdown by LkSG complaint category
    - Overdue complaint count
    - Overall resolution rate

    Only considers reports submitted via the ``lksg`` channel.

    Requires ``dashboard:read`` scope.
    """
    lksg_filter = [Report.channel == Channel.LKSG]

    # Total LkSG complaints
    total_stmt = select(func.count()).select_from(Report).where(
        Report.channel == Channel.LKSG
    )
    total_result = await db.execute(total_stmt)
    total_complaints = total_result.scalar_one()

    # Resolved (abgeschlossen)
    resolved_stmt = select(func.count()).select_from(Report).where(
        Report.channel == Channel.LKSG,
        Report.status == ReportStatus.ABGESCHLOSSEN,
    )
    resolved_result = await db.execute(resolved_stmt)
    resolved_complaints = resolved_result.scalar_one()

    # Pending (not abgeschlossen)
    pending_complaints = total_complaints - resolved_complaints

    # Average resolution time for LkSG cases
    avg_days = await _avg_resolution_days(db, extra_filters=lksg_filter)

    # Count by LkSG category
    category_stmt = (
        select(Report.lksg_category, func.count())
        .where(
            Report.channel == Channel.LKSG,
            Report.lksg_category.isnot(None),
        )
        .group_by(Report.lksg_category)
    )
    category_result = await db.execute(category_stmt)
    by_category = [
        LkSGCategoryCount(
            category=row[0].value if hasattr(row[0], "value") else str(row[0]),
            count=row[1],
        )
        for row in category_result.all()
    ]

    # Overdue LkSG complaints
    now = func.now()
    overdue_stmt = select(func.count()).select_from(Report).where(
        Report.channel == Channel.LKSG,
        (
            (Report.confirmation_deadline < now)
            & (Report.confirmation_sent_at.is_(None))
        )
        | (
            (Report.feedback_deadline < now)
            & (Report.feedback_sent_at.is_(None))
        ),
    )
    overdue_result = await db.execute(overdue_stmt)
    overdue_count = overdue_result.scalar_one()

    # Resolution rate
    resolution_rate = (
        round((resolved_complaints / total_complaints) * 100.0, 1)
        if total_complaints > 0
        else 0.0
    )

    logger.info(
        "admin_lksg_effectiveness_viewed",
        user_email=user.email,
        total_complaints=total_complaints,
        resolution_rate=resolution_rate,
    )

    return LkSGEffectivenessResponse(
        total_complaints=total_complaints,
        resolved_complaints=resolved_complaints,
        pending_complaints=pending_complaints,
        avg_resolution_days=avg_days,
        by_category=by_category,
        overdue_count=overdue_count,
        resolution_rate=resolution_rate,
    )


# -- GET /admin/reports/lksg-annual -------------------------------------------


@router.get(
    "/admin/reports/lksg-annual",
    response_model=LkSGAnnualReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get LkSG annual report data",
    responses={
        403: {"description": "Insufficient permissions"},
    },
)
async def get_lksg_annual_report(
    user=Security(get_current_user, scopes=["dashboard:read"]),
    tenant_id: Annotated[uuid.UUID, Depends(get_current_tenant)] = ...,
    db: Annotated[AsyncSession, Depends(get_tenant_db)] = ...,
    year: int = Query(
        default=None,
        description=(
            "Reporting year (defaults to current year). "
            "Used to filter complaints by creation date."
        ),
    ),
) -> LkSGAnnualReportResponse:
    """Return annual report data for LkSG compliance.

    Provides data points required for the annual effectiveness report
    mandated by LkSG Section 10 para. 2, including:
    - Complaint counts (total, resolved, pending) for the year
    - Average resolution time
    - Breakdown by LkSG category and status
    - Resolution rate
    - Count of cases with documented remedial measures

    Only considers reports submitted via the ``lksg`` channel within
    the specified reporting year.

    Requires ``dashboard:read`` scope.
    """
    if year is None:
        year = datetime.now(UTC).year

    # Date range for the reporting year
    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)

    year_filters = [
        Report.channel == Channel.LKSG,
        Report.created_at >= year_start,
        Report.created_at < year_end,
    ]

    # Total LkSG complaints in the year
    total_stmt = select(func.count()).select_from(Report).where(*year_filters)
    total_result = await db.execute(total_stmt)
    total_complaints = total_result.scalar_one()

    # Resolved in the year
    resolved_stmt = select(func.count()).select_from(Report).where(
        *year_filters,
        Report.status == ReportStatus.ABGESCHLOSSEN,
    )
    resolved_result = await db.execute(resolved_stmt)
    resolved_complaints = resolved_result.scalar_one()

    # Pending at year end
    pending_complaints = total_complaints - resolved_complaints

    # Average resolution time for the year
    avg_days = await _avg_resolution_days(db, extra_filters=year_filters)

    # By LkSG category
    category_stmt = (
        select(Report.lksg_category, func.count())
        .where(*year_filters, Report.lksg_category.isnot(None))
        .group_by(Report.lksg_category)
    )
    category_result = await db.execute(category_stmt)
    by_category = [
        LkSGCategoryCount(
            category=row[0].value if hasattr(row[0], "value") else str(row[0]),
            count=row[1],
        )
        for row in category_result.all()
    ]

    # By status
    status_stmt = (
        select(Report.status, func.count())
        .where(*year_filters)
        .group_by(Report.status)
    )
    status_result = await db.execute(status_stmt)
    by_status = [
        StatusCount(status=row[0].value, count=row[1])
        for row in status_result.all()
    ]

    # Resolution rate
    resolution_rate = (
        round((resolved_complaints / total_complaints) * 100.0, 1)
        if total_complaints > 0
        else 0.0
    )

    # Measures taken: cases that progressed to rueckmeldung or
    # abgeschlossen indicate remedial measures were documented
    measures_stmt = select(func.count()).select_from(Report).where(
        *year_filters,
        Report.status.in_([
            ReportStatus.RUECKMELDUNG,
            ReportStatus.ABGESCHLOSSEN,
        ]),
    )
    measures_result = await db.execute(measures_stmt)
    measures_taken = measures_result.scalar_one()

    logger.info(
        "admin_lksg_annual_report_viewed",
        user_email=user.email,
        year=year,
        total_complaints=total_complaints,
    )

    return LkSGAnnualReportResponse(
        year=year,
        total_complaints=total_complaints,
        resolved_complaints=resolved_complaints,
        pending_complaints=pending_complaints,
        avg_resolution_days=avg_days,
        by_category=by_category,
        by_status=by_status,
        resolution_rate=resolution_rate,
        measures_taken=measures_taken,
    )
