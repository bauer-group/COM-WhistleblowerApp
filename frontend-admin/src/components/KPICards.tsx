/**
 * Hinweisgebersystem – KPI Card Components.
 *
 * Reusable metric card components for the admin dashboard.
 * Each card displays a label, a numeric value, and an optional
 * trend indicator (arrow + percentage).  Supports custom accent
 * colors for visual categorization.
 *
 * Used by the Dashboard page to display total cases, open cases,
 * overdue cases, and average resolution time.
 */

import type { ReactNode } from 'react';

// ── Types ─────────────────────────────────────────────────────

export type TrendDirection = 'up' | 'down' | 'neutral';

export interface KPICardData {
  /** Unique key for React list rendering */
  key: string;
  /** Human-readable metric label */
  label: string;
  /** Formatted metric value (e.g. "42", "3.5 Tage") */
  value: string | number;
  /** Optional trend percentage (e.g. 12.5 for +12.5%) */
  trendPercent?: number;
  /** Trend direction: up/down/neutral */
  trendDirection?: TrendDirection;
  /** Tailwind accent color class (e.g. "text-primary", "text-danger") */
  accentColor?: string;
  /** Optional icon node rendered beside the value */
  icon?: ReactNode;
}

interface KPICardProps {
  data: KPICardData;
}

interface KPICardsGridProps {
  cards: KPICardData[];
}

// ── Trend Arrow ───────────────────────────────────────────────

function TrendArrow({ direction }: { direction: TrendDirection }) {
  if (direction === 'up') {
    return (
      <svg
        className="h-4 w-4"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M10 17a.75.75 0 01-.75-.75V5.612L5.29 9.77a.75.75 0 01-1.08-1.04l5.25-5.5a.75.75 0 011.08 0l5.25 5.5a.75.75 0 11-1.08 1.04l-3.96-4.158V16.25A.75.75 0 0110 17z"
          clipRule="evenodd"
        />
      </svg>
    );
  }

  if (direction === 'down') {
    return (
      <svg
        className="h-4 w-4"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M10 3a.75.75 0 01.75.75v10.638l3.96-4.158a.75.75 0 111.08 1.04l-5.25 5.5a.75.75 0 01-1.08 0l-5.25-5.5a.75.75 0 111.08-1.04l3.96 4.158V3.75A.75.75 0 0110 3z"
          clipRule="evenodd"
        />
      </svg>
    );
  }

  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M4 10a.75.75 0 01.75-.75h10.5a.75.75 0 010 1.5H4.75A.75.75 0 014 10z"
        clipRule="evenodd"
      />
    </svg>
  );
}

// ── Trend Badge ───────────────────────────────────────────────

function TrendBadge({
  direction,
  percent,
}: {
  direction: TrendDirection;
  percent: number;
}) {
  const colorClass =
    direction === 'up'
      ? 'text-success bg-success/10'
      : direction === 'down'
        ? 'text-danger bg-danger/10'
        : 'text-neutral-500 bg-neutral-100';

  const sign = direction === 'up' ? '+' : direction === 'down' ? '-' : '';
  const formattedPercent = Math.abs(percent).toFixed(1);

  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${colorClass}`}
      aria-label={`Trend: ${sign}${formattedPercent}%`}
    >
      <TrendArrow direction={direction} />
      {sign}{formattedPercent}%
    </span>
  );
}

// ── Single KPI Card ───────────────────────────────────────────

/**
 * Individual KPI metric card with value, label, and optional trend.
 *
 * Renders a bordered card with the metric value prominently displayed,
 * the label below, and an optional trend badge in the top-right corner.
 */
export function KPICard({ data }: KPICardProps) {
  const {
    label,
    value,
    trendPercent,
    trendDirection = 'neutral',
    accentColor = 'text-neutral-900',
    icon,
  } = data;

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          {icon && (
            <div className={`${accentColor} opacity-80`}>{icon}</div>
          )}
          <div>
            <p className="text-sm font-medium text-neutral-500">{label}</p>
            <p className={`mt-1 text-3xl font-bold ${accentColor}`}>
              {value}
            </p>
          </div>
        </div>

        {trendPercent !== undefined && (
          <TrendBadge direction={trendDirection} percent={trendPercent} />
        )}
      </div>
    </div>
  );
}

// ── KPI Cards Grid ────────────────────────────────────────────

/**
 * Responsive grid layout for multiple KPI cards.
 *
 * Renders cards in a 1-column layout on mobile, 2 columns on
 * medium screens, and 4 columns on large screens.
 */
export default function KPICards({ cards }: KPICardsGridProps) {
  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      role="region"
      aria-label="Leistungskennzahlen"
    >
      {cards.map((card) => (
        <KPICard key={card.key} data={card} />
      ))}
    </div>
  );
}
