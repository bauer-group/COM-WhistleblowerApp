/**
 * Hinweisgebersystem – Reusable Case Table Component.
 *
 * Sortable, paginated table for displaying case list items.
 * Features:
 * - Column-based sorting with visual indicators
 * - Row click navigation to case detail
 * - Deadline highlighting (yellow for approaching, red for overdue)
 * - Status and priority badges with semantic colors
 * - Responsive layout with horizontal scroll on small screens
 * - Pagination controls with page size selector
 *
 * Used by both the Dashboard (recent cases) and CaseList pages.
 */

import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import type { CaseListItem, PaginationMeta, ReportStatus, Priority, Channel } from '@/api/cases';
import LabelBadge from '@/components/LabelBadge';

// ── Types ─────────────────────────────────────────────────────

export interface SortConfig {
  sort_by: string;
  sort_desc: boolean;
}

interface CaseTableProps {
  /** Array of case items to display */
  cases: CaseListItem[];
  /** Current sort configuration */
  sort: SortConfig;
  /** Callback when a column header is clicked for sorting */
  onSortChange: (sort: SortConfig) => void;
  /** Pagination metadata (optional — hides pagination controls if absent) */
  pagination?: PaginationMeta;
  /** Callback when page changes */
  onPageChange?: (page: number) => void;
  /** Whether the table data is loading */
  isLoading?: boolean;
}

// ── Status & Priority Badge Helpers ───────────────────────────

const STATUS_LABELS: Record<ReportStatus, string> = {
  eingegangen: 'Eingegangen',
  in_pruefung: 'In Prüfung',
  in_bearbeitung: 'In Bearbeitung',
  rueckmeldung: 'Rückmeldung',
  abgeschlossen: 'Abgeschlossen',
};

const STATUS_COLORS: Record<ReportStatus, string> = {
  eingegangen: 'bg-blue-100 text-blue-800',
  in_pruefung: 'bg-yellow-100 text-yellow-800',
  in_bearbeitung: 'bg-orange-100 text-orange-800',
  rueckmeldung: 'bg-purple-100 text-purple-800',
  abgeschlossen: 'bg-green-100 text-green-800',
};

const PRIORITY_LABELS: Record<Priority, string> = {
  low: 'Niedrig',
  medium: 'Mittel',
  high: 'Hoch',
  critical: 'Kritisch',
};

const PRIORITY_COLORS: Record<Priority, string> = {
  low: 'bg-neutral-100 text-neutral-700',
  medium: 'bg-blue-100 text-blue-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
};

const CHANNEL_LABELS: Record<Channel, string> = {
  hinschg: 'HinSchG',
  lksg: 'LkSG',
};

// ── Column Definitions ────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  sortable: boolean;
  className?: string;
}

const COLUMNS: ColumnDef[] = [
  { key: 'case_number', label: 'Fall-Nr.', sortable: true },
  { key: 'status', label: 'Status', sortable: true },
  { key: 'priority', label: 'Priorität', sortable: true },
  { key: 'channel', label: 'Kanal', sortable: true },
  { key: 'category', label: 'Kategorie', sortable: true },
  { key: 'subject', label: 'Betreff', sortable: false, className: 'max-w-[200px] truncate' },
  { key: 'labels', label: 'Labels', sortable: false },
  { key: 'created_at', label: 'Erstellt', sortable: true },
  { key: 'confirmation_deadline', label: 'Frist', sortable: true },
];

// ── Sort Header ───────────────────────────────────────────────

function SortIcon({ active, desc }: { active: boolean; desc: boolean }) {
  if (!active) {
    return (
      <svg
        className="ml-1 h-4 w-4 text-neutral-400"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M7 8l3-3 3 3M7 12l3 3 3-3" stroke="currentColor" strokeWidth="1.5" fill="none" />
      </svg>
    );
  }

  return (
    <svg
      className="ml-1 h-4 w-4 text-primary"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      {desc ? (
        <path
          fillRule="evenodd"
          d="M10 3a.75.75 0 01.75.75v10.638l3.96-4.158a.75.75 0 111.08 1.04l-5.25 5.5a.75.75 0 01-1.08 0l-5.25-5.5a.75.75 0 111.08-1.04l3.96 4.158V3.75A.75.75 0 0110 3z"
          clipRule="evenodd"
        />
      ) : (
        <path
          fillRule="evenodd"
          d="M10 17a.75.75 0 01-.75-.75V5.612L5.29 9.77a.75.75 0 01-1.08-1.04l5.25-5.5a.75.75 0 011.08 0l5.25 5.5a.75.75 0 11-1.08 1.04l-3.96-4.158V16.25A.75.75 0 0110 17z"
          clipRule="evenodd"
        />
      )}
    </svg>
  );
}

// ── Deadline Highlighting ─────────────────────────────────────

/**
 * Determine deadline highlighting CSS class.
 *
 * - Red background for overdue deadlines
 * - Yellow background for deadlines within 7 days
 * - No highlighting otherwise
 */
function getDeadlineClass(
  item: CaseListItem,
): string {
  if (item.is_overdue_confirmation || item.is_overdue_feedback) {
    return 'bg-red-50 text-red-700 font-medium';
  }

  // Check if confirmation deadline is within 7 days
  if (item.confirmation_deadline && !item.confirmation_sent_at) {
    const deadline = new Date(item.confirmation_deadline);
    const now = new Date();
    const daysUntil = (deadline.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);

    if (daysUntil <= 7 && daysUntil > 0) {
      return 'bg-yellow-50 text-yellow-700 font-medium';
    }
  }

  // Check if feedback deadline is within 90 days (3 months)
  if (item.feedback_deadline && !item.feedback_sent_at) {
    const deadline = new Date(item.feedback_deadline);
    const now = new Date();
    const daysUntil = (deadline.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);

    if (daysUntil <= 90 && daysUntil > 0) {
      return 'bg-yellow-50 text-yellow-700 font-medium';
    }
  }

  return '';
}

/**
 * Format a deadline date with remaining days context.
 */
function formatDeadline(item: CaseListItem): string {
  const deadline = item.confirmation_deadline ?? item.feedback_deadline;
  if (!deadline) return '\u2013';

  const date = new Date(deadline);
  const now = new Date();
  const daysUntil = Math.ceil(
    (date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24),
  );

  const formatted = date.toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  if (daysUntil < 0) {
    return `${formatted} (${Math.abs(daysUntil)}d überfällig)`;
  }
  if (daysUntil === 0) {
    return `${formatted} (heute)`;
  }
  if (daysUntil <= 7) {
    return `${formatted} (${daysUntil}d)`;
  }

  return formatted;
}

// ── Pagination Controls ───────────────────────────────────────

function PaginationControls({
  pagination,
  onPageChange,
}: {
  pagination: PaginationMeta;
  onPageChange: (page: number) => void;
}) {
  const { page, total_pages, total } = pagination;

  return (
    <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3">
      <p className="text-sm text-neutral-600">
        {total} {total === 1 ? 'Fall' : 'Fälle'} gesamt
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Vorherige Seite"
        >
          Zurück
        </button>

        <span className="text-sm text-neutral-600">
          Seite {page} von {total_pages}
        </span>

        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= total_pages}
          className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Nächste Seite"
        >
          Weiter
        </button>
      </div>
    </div>
  );
}

// ── Loading Skeleton ──────────────────────────────────────────

function TableSkeleton() {
  return (
    <div className="animate-pulse" role="status" aria-label="Daten werden geladen...">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex gap-4 border-b border-neutral-100 px-4 py-4"
        >
          <div className="h-4 w-20 rounded bg-neutral-200" />
          <div className="h-4 w-24 rounded bg-neutral-200" />
          <div className="h-4 w-16 rounded bg-neutral-200" />
          <div className="h-4 w-16 rounded bg-neutral-200" />
          <div className="h-4 w-24 rounded bg-neutral-200" />
          <div className="h-4 flex-1 rounded bg-neutral-200" />
          <div className="h-4 w-20 rounded bg-neutral-200" />
          <div className="h-4 w-28 rounded bg-neutral-200" />
        </div>
      ))}
    </div>
  );
}

// ── CaseTable Component ───────────────────────────────────────

/**
 * Reusable sortable table for case list items.
 *
 * Renders a table with sortable column headers, status/priority
 * badges, deadline highlighting, and row click navigation to the
 * case detail page.  Supports optional pagination controls.
 */
export default function CaseTable({
  cases,
  sort,
  onSortChange,
  pagination,
  onPageChange,
  isLoading = false,
}: CaseTableProps) {
  const navigate = useNavigate();

  const handleSort = useCallback(
    (columnKey: string) => {
      if (sort.sort_by === columnKey) {
        onSortChange({ sort_by: columnKey, sort_desc: !sort.sort_desc });
      } else {
        onSortChange({ sort_by: columnKey, sort_desc: true });
      }
    },
    [sort, onSortChange],
  );

  const handleRowClick = useCallback(
    (caseId: string) => {
      void navigate(`/cases/${caseId}`);
    },
    [navigate],
  );

  const handleRowKeyDown = useCallback(
    (e: React.KeyboardEvent, caseId: string) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        void navigate(`/cases/${caseId}`);
      }
    },
    [navigate],
  );

  return (
    <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-neutral-200 bg-neutral-50">
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className={`px-4 py-3 text-xs font-semibold uppercase tracking-wider text-neutral-600 ${
                    col.sortable
                      ? 'cursor-pointer select-none hover:bg-neutral-100'
                      : ''
                  }`}
                  onClick={
                    col.sortable ? () => handleSort(col.key) : undefined
                  }
                  aria-sort={
                    sort.sort_by === col.key
                      ? sort.sort_desc
                        ? 'descending'
                        : 'ascending'
                      : undefined
                  }
                >
                  <div className="flex items-center">
                    {col.label}
                    {col.sortable && (
                      <SortIcon
                        active={sort.sort_by === col.key}
                        desc={sort.sort_desc}
                      />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-neutral-100">
            {isLoading ? (
              <tr>
                <td colSpan={COLUMNS.length}>
                  <TableSkeleton />
                </td>
              </tr>
            ) : cases.length === 0 ? (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-4 py-12 text-center text-neutral-500"
                >
                  Keine Fälle gefunden.
                </td>
              </tr>
            ) : (
              cases.map((item) => {
                const deadlineClass = getDeadlineClass(item);

                return (
                  <tr
                    key={item.id}
                    onClick={() => handleRowClick(item.id)}
                    onKeyDown={(e) => handleRowKeyDown(e, item.id)}
                    tabIndex={0}
                    role="link"
                    aria-label={`Fall ${item.case_number} öffnen`}
                    className={`cursor-pointer transition-colors hover:bg-neutral-50 ${deadlineClass}`}
                  >
                    {/* Case Number */}
                    <td className="whitespace-nowrap px-4 py-3 font-medium text-primary">
                      {item.case_number}
                      {item.unread_count > 0 && (
                        <span
                          className="ml-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary text-xs text-white"
                          aria-label={`${item.unread_count} ungelesene Nachrichten`}
                        >
                          {item.unread_count}
                        </span>
                      )}
                    </td>

                    {/* Status */}
                    <td className="whitespace-nowrap px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[item.status]}`}
                      >
                        {STATUS_LABELS[item.status]}
                      </span>
                    </td>

                    {/* Priority */}
                    <td className="whitespace-nowrap px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${PRIORITY_COLORS[item.priority]}`}
                      >
                        {PRIORITY_LABELS[item.priority]}
                      </span>
                    </td>

                    {/* Channel */}
                    <td className="whitespace-nowrap px-4 py-3 text-neutral-700">
                      {CHANNEL_LABELS[item.channel]}
                    </td>

                    {/* Category */}
                    <td className="whitespace-nowrap px-4 py-3 text-neutral-600">
                      {item.category ?? '\u2013'}
                    </td>

                    {/* Subject */}
                    <td className="max-w-[200px] truncate px-4 py-3 text-neutral-700">
                      {item.subject ?? '\u2013'}
                    </td>

                    {/* Labels */}
                    <td className="px-4 py-3">
                      {item.labels && item.labels.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {item.labels.map((label) => (
                            <LabelBadge
                              key={label.id}
                              name={label.name}
                              color={label.color}
                              size="sm"
                            />
                          ))}
                        </div>
                      ) : (
                        <span className="text-neutral-400">{'\u2013'}</span>
                      )}
                    </td>

                    {/* Created At */}
                    <td className="whitespace-nowrap px-4 py-3 text-neutral-600">
                      {new Date(item.created_at).toLocaleDateString('de-DE', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                      })}
                    </td>

                    {/* Deadline */}
                    <td className="whitespace-nowrap px-4 py-3 text-neutral-600">
                      {formatDeadline(item)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {pagination && onPageChange && (
        <PaginationControls
          pagination={pagination}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}
