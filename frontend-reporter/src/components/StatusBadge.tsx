/**
 * Hinweisgebersystem - StatusBadge Component.
 *
 * Displays the current case status with color coding.
 * Status values mirror the backend ReportStatus enum:
 *   eingegangen, in_pruefung, in_bearbeitung, rueckmeldung, abgeschlossen
 *
 * WCAG 2.1 AA compliant:
 * - Uses role="status" for screen reader announcements
 * - Translated status labels via i18n
 * - 4.5:1 contrast ratio on all color combinations
 * - Visible text with color-blind-friendly design (not color-only)
 */

import { useTranslation } from 'react-i18next';

import type { ReportStatus } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

interface StatusBadgeProps {
  /** Case status value from the backend. */
  status: ReportStatus;
  /** Optional size variant. */
  size?: 'sm' | 'md';
}

// ── Status styling ────────────────────────────────────────────

interface StatusStyle {
  bg: string;
  text: string;
  dot: string;
}

const statusStyles: Record<ReportStatus, StatusStyle> = {
  eingegangen: {
    bg: 'bg-blue-50',
    text: 'text-blue-800',
    dot: 'bg-blue-500',
  },
  in_pruefung: {
    bg: 'bg-amber-50',
    text: 'text-amber-800',
    dot: 'bg-amber-500',
  },
  in_bearbeitung: {
    bg: 'bg-purple-50',
    text: 'text-purple-800',
    dot: 'bg-purple-500',
  },
  rueckmeldung: {
    bg: 'bg-emerald-50',
    text: 'text-emerald-800',
    dot: 'bg-emerald-500',
  },
  abgeschlossen: {
    bg: 'bg-neutral-100',
    text: 'text-neutral-700',
    dot: 'bg-neutral-500',
  },
};

/** i18n keys for each status value. */
const statusLabelKeys: Record<ReportStatus, string> = {
  eingegangen: 'common:status.eingegangen',
  in_pruefung: 'common:status.in_pruefung',
  in_bearbeitung: 'common:status.in_bearbeitung',
  rueckmeldung: 'common:status.rueckmeldung',
  abgeschlossen: 'common:status.abgeschlossen',
};

/** Fallback labels (German) in case translations are not loaded. */
const statusFallbacks: Record<ReportStatus, string> = {
  eingegangen: 'Eingegangen',
  in_pruefung: 'In Prüfung',
  in_bearbeitung: 'In Bearbeitung',
  rueckmeldung: 'Rückmeldung',
  abgeschlossen: 'Abgeschlossen',
};

// ── Component ─────────────────────────────────────────────────

export default function StatusBadge({
  status,
  size = 'md',
}: StatusBadgeProps) {
  const { t } = useTranslation();
  const styles = statusStyles[status] ?? statusStyles.eingegangen;
  const label = t(statusLabelKeys[status], statusFallbacks[status]);

  const sizeClasses = size === 'sm'
    ? 'px-2 py-0.5 text-xs'
    : 'px-2.5 py-1 text-sm';

  return (
    <span
      role="status"
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${styles.bg} ${styles.text} ${sizeClasses}`}
    >
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${styles.dot}`}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
