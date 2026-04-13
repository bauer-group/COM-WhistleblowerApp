/**
 * Hinweisgebersystem – Admin Dashboard Page.
 *
 * Displays an overview of the whistleblower case management system:
 * - KPI cards: total cases, open cases, overdue cases, average resolution time
 *   with trend indicators calculated from monthly data
 * - Case distribution charts by status and channel
 * - Recent cases table with quick access to case details
 *
 * Data is fetched via TanStack Query hooks and auto-refreshes
 * every 60 seconds (dashboard stats) and 30 seconds (case list).
 */

import { useMemo } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useDashboardStats, useCases } from '@/hooks/useCases';
import KPICards from '@/components/KPICards';
import type { KPICardData, TrendDirection } from '@/components/KPICards';
import CaseTable from '@/components/CaseTable';
import type { SortConfig } from '@/components/CaseTable';
import type { DashboardStatsResponse, StatusCount, ChannelCount } from '@/api/cases';

// ── KPI Data Builder ──────────────────────────────────────────

/**
 * Calculate trend direction and percentage from monthly trend data.
 *
 * Compares the last two months in the trend array to determine
 * whether case volume is increasing, decreasing, or stable.
 */
function calculateTrend(
  monthly: DashboardStatsResponse['monthly_trend'],
): { direction: TrendDirection; percent: number } {
  if (!monthly || monthly.length < 2) {
    return { direction: 'neutral', percent: 0 };
  }

  const current = monthly[monthly.length - 1].count;
  const previous = monthly[monthly.length - 2].count;

  if (previous === 0) {
    return current > 0
      ? { direction: 'up', percent: 100 }
      : { direction: 'neutral', percent: 0 };
  }

  const changePercent = ((current - previous) / previous) * 100;

  if (Math.abs(changePercent) < 1) {
    return { direction: 'neutral', percent: 0 };
  }

  return {
    direction: changePercent > 0 ? 'up' : 'down',
    percent: Math.abs(changePercent),
  };
}

function buildKPICards(stats: DashboardStatsResponse, t: (key: string, fallback?: string) => string): KPICardData[] {
  const trend = calculateTrend(stats.monthly_trend);

  const openStatuses = ['eingegangen', 'in_pruefung', 'in_bearbeitung', 'rueckmeldung'];
  const openCases = stats.by_status
    .filter((s) => openStatuses.includes(s.status))
    .reduce((sum, s) => sum + s.count, 0);

  return [
    {
      key: 'total',
      label: t('dashboard.kpi.total_cases', 'Fälle gesamt'),
      value: stats.total_cases,
      trendPercent: trend.percent,
      trendDirection: trend.direction,
      accentColor: 'text-primary',
    },
    {
      key: 'open',
      label: t('dashboard.kpi.open_cases', 'Offene Fälle'),
      value: openCases,
      accentColor: 'text-warning',
    },
    {
      key: 'overdue',
      label: t('dashboard.kpi.overdue_cases', 'Überfällige Fälle'),
      value: stats.overdue_count,
      accentColor: stats.overdue_count > 0 ? 'text-danger' : 'text-success',
    },
    {
      key: 'resolution',
      label: t('dashboard.kpi.avg_resolution', 'Ø Bearbeitungszeit'),
      value:
        stats.avg_resolution_days !== null
          ? `${stats.avg_resolution_days.toFixed(1)} Tage`
          : '\u2013',
      accentColor: 'text-neutral-900',
    },
  ];
}

// ── Distribution Bar Chart ────────────────────────────────────

/**
 * Horizontal bar chart showing distribution of cases.
 *
 * Used for both status and channel distribution. Renders colored
 * bars proportional to the count relative to the maximum value.
 */
function DistributionChart({
  title,
  data,
  colorMap,
  labelMap,
}: {
  title: string;
  data: { key: string; count: number }[];
  colorMap: Record<string, string>;
  labelMap: Record<string, string>;
}) {
  const maxCount = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-neutral-600">
        {title}
      </h3>
      <div className="space-y-3">
        {data.map((item) => (
          <div key={item.key}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="text-neutral-700">
                {labelMap[item.key] ?? item.key}
              </span>
              <span className="font-medium text-neutral-900">
                {item.count}
              </span>
            </div>
            <div className="h-2.5 w-full rounded-full bg-neutral-100">
              <div
                className={`h-2.5 rounded-full transition-all ${colorMap[item.key] ?? 'bg-neutral-400'}`}
                style={{
                  width: `${(item.count / maxCount) * 100}%`,
                }}
                role="progressbar"
                aria-valuenow={item.count}
                aria-valuemax={maxCount}
                aria-label={`${labelMap[item.key] ?? item.key}: ${item.count}`}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Status Distribution Colors ────────────────────────────────

const STATUS_BAR_COLORS: Record<string, string> = {
  eingegangen: 'bg-blue-500',
  in_pruefung: 'bg-yellow-500',
  in_bearbeitung: 'bg-orange-500',
  rueckmeldung: 'bg-purple-500',
  abgeschlossen: 'bg-green-500',
};

const CHANNEL_BAR_COLORS: Record<string, string> = {
  hinschg: 'bg-primary',
  lksg: 'bg-primary-light',
};

// ── Dashboard Page ────────────────────────────────────────────

/**
 * Admin dashboard displaying KPIs, distribution charts, and recent cases.
 *
 * Fetches dashboard statistics and the 10 most recent cases.
 * Data auto-refreshes on configurable intervals via TanStack Query.
 */
export default function Dashboard() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useDashboardStats();
  const { data: recentCases, isLoading: casesLoading } = useCases({
    params: { page: 1, page_size: 10, sort_by: 'created_at', sort_desc: true },
  });
  const { t } = useTranslation('cases');

  const kpiCards = useMemo<KPICardData[]>(() => {
    if (!stats) return [];
    return buildKPICards(stats, t);
  }, [stats, t]);

  const statusData = useMemo(() => {
    if (!stats) return [];
    return stats.by_status.map((s: StatusCount) => ({
      key: s.status,
      count: s.count,
    }));
  }, [stats]);

  const channelData = useMemo(() => {
    if (!stats) return [];
    return stats.by_channel.map((c: ChannelCount) => ({
      key: c.channel,
      count: c.count,
    }));
  }, [stats]);

  // Recent cases table uses a fixed sort (newest first) — no user interaction
  const recentSort: SortConfig = { sort_by: 'created_at', sort_desc: true };

  if (statsError) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div
          className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center"
          role="alert"
        >
          <h2 className="text-lg font-semibold text-danger">
            {t('dashboard.error.title', 'Fehler beim Laden des Dashboards')}
          </h2>
          <p className="mt-2 text-neutral-600">
            {t('dashboard.error.message', 'Die Dashboard-Daten konnten nicht geladen werden. Bitte versuchen Sie es später erneut.')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-neutral-900">{t('dashboard.title', 'Dashboard')}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          {t('dashboard.subtitle', 'Übersicht aller Meldungen und Leistungskennzahlen')}
        </p>
      </div>

      {/* KPI Cards */}
      {statsLoading ? (
        <div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
          role="status"
          aria-label="Kennzahlen werden geladen..."
        >
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="animate-pulse rounded-lg border border-neutral-200 bg-white p-6 shadow-sm"
            >
              <div className="h-4 w-24 rounded bg-neutral-200" />
              <div className="mt-3 h-8 w-16 rounded bg-neutral-200" />
            </div>
          ))}
        </div>
      ) : (
        <KPICards cards={kpiCards} />
      )}

      {/* Distribution Charts */}
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {statsLoading ? (
          <>
            <div className="animate-pulse rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
              <div className="h-4 w-32 rounded bg-neutral-200" />
              <div className="mt-4 space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-6 rounded bg-neutral-200" />
                ))}
              </div>
            </div>
            <div className="animate-pulse rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
              <div className="h-4 w-32 rounded bg-neutral-200" />
              <div className="mt-4 space-y-3">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div key={i} className="h-6 rounded bg-neutral-200" />
                ))}
              </div>
            </div>
          </>
        ) : (
          <>
            <DistributionChart
              title={t('dashboard.charts.status_distribution', 'Verteilung nach Status')}
              data={statusData}
              colorMap={STATUS_BAR_COLORS}
              labelMap={{
                eingegangen: t('common:status.eingegangen', 'Eingegangen'),
                in_pruefung: t('common:status.in_pruefung', 'In Prüfung'),
                in_bearbeitung: t('common:status.in_bearbeitung', 'In Bearbeitung'),
                rueckmeldung: t('common:status.rueckmeldung', 'Rückmeldung'),
                abgeschlossen: t('common:status.abgeschlossen', 'Abgeschlossen'),
              }}
            />
            <DistributionChart
              title={t('dashboard.charts.channel_distribution', 'Verteilung nach Kanal')}
              data={channelData}
              colorMap={CHANNEL_BAR_COLORS}
              labelMap={{
                hinschg: t('dashboard.channel_hinschg', 'HinSchG (intern)'),
                lksg: t('dashboard.channel_lksg', 'LkSG (öffentlich)'),
              }}
            />
          </>
        )}
      </div>

      {/* Recent Cases */}
      <div className="mt-8">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-neutral-900">
            {t('dashboard.recent_cases', 'Neueste Fälle')}
          </h2>
          <Link
            to="/cases"
            className="text-sm font-medium text-primary transition-colors hover:text-primary-dark"
          >
            {t('dashboard.view_all_cases', 'Alle Fälle anzeigen')} &rarr;
          </Link>
        </div>

        <CaseTable
          cases={recentCases?.items ?? []}
          sort={recentSort}
          onSortChange={() => {
            /* Dashboard uses fixed sort — navigating to /cases for full control */
          }}
          isLoading={casesLoading}
        />
      </div>
    </div>
  );
}
