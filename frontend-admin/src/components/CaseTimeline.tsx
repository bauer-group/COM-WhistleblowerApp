/**
 * Hinweisgebersystem – Case Timeline Component.
 *
 * Chronological communication timeline displaying all events for a case:
 * - Reporter messages (left-aligned, blue accent)
 * - Handler messages (right-aligned, primary accent)
 * - Internal notes (right-aligned, amber accent, marked as internal)
 * - System events / status changes (centered, neutral accent)
 * - Audit log entries (centered, gray)
 *
 * Messages and audit entries are merged and sorted chronologically.
 * Each entry is rendered as a semantic <article> element with
 * appropriate ARIA labeling for screen reader accessibility.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type {
  MessageResponse,
  AuditLogEntry,
  SenderType,
  AttachmentSummary,
} from '@/api/cases';

// ── Types ─────────────────────────────────────────────────────

interface CaseTimelineProps {
  /** Messages (both public and internal) for the case. */
  messages: MessageResponse[];
  /** Audit trail entries for the case. */
  auditTrail: AuditLogEntry[];
  /** Whether to show internal notes in the timeline. */
  showInternalNotes?: boolean;
  /** Filter: show only specific event types (null = show all). */
  filter?: TimelineFilter | null;
}

export type TimelineFilter = 'messages' | 'notes' | 'audit' | 'all';

// ── Timeline Entry Types ─────────────────────────────────────

interface TimelineEntry {
  id: string;
  type: 'message' | 'note' | 'audit';
  timestamp: string;
  content: string | null;
  senderType?: SenderType;
  senderUserId?: string | null;
  isInternal?: boolean;
  isRead?: boolean;
  attachments?: AttachmentSummary[];
  auditAction?: string;
  auditDetails?: Record<string, unknown> | null;
  actorType?: string;
}

// ── Merge & Sort Helpers ─────────────────────────────────────

function mergeEntries(
  messages: MessageResponse[],
  auditTrail: AuditLogEntry[],
  showInternalNotes: boolean,
  filter: TimelineFilter | null,
): TimelineEntry[] {
  const entries: TimelineEntry[] = [];

  for (const msg of messages) {
    const isNote = msg.is_internal;

    // Apply filter
    if (filter === 'messages' && isNote) continue;
    if (filter === 'notes' && !isNote) continue;
    if (filter === 'audit') continue;

    // Skip internal notes if not showing them
    if (isNote && !showInternalNotes) continue;

    entries.push({
      id: msg.id,
      type: isNote ? 'note' : 'message',
      timestamp: msg.created_at,
      content: msg.content,
      senderType: msg.sender_type,
      senderUserId: msg.sender_user_id,
      isInternal: msg.is_internal,
      isRead: msg.is_read,
      attachments: msg.attachments,
    });
  }

  if (filter !== 'messages' && filter !== 'notes') {
    for (const entry of auditTrail) {
      entries.push({
        id: entry.id,
        type: 'audit',
        timestamp: entry.created_at,
        content: null,
        auditAction: entry.action,
        auditDetails: entry.details,
        actorType: entry.actor_type,
      });
    }
  }

  // Sort chronologically (oldest first)
  entries.sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );

  return entries;
}

// ── Date Formatting ──────────────────────────────────────────

function formatTimestamp(iso: string, locale: string = 'de-DE'): string {
  try {
    const date = new Date(iso);
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  } catch {
    return iso;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Audit Detail Helper ─────────────────────────────────────

function getAuditDetail(
  details: Record<string, unknown> | null,
  t: TFunction,
): string | null {
  if (!details) return null;

  if (details['old_status'] && details['new_status']) {
    const oldLabel = t('common:status.' + (details['old_status'] as string), details['old_status'] as string);
    const newLabel = t('common:status.' + (details['new_status'] as string), details['new_status'] as string);
    return `${oldLabel} \u2192 ${newLabel}`;
  }

  if (details['old_priority'] && details['new_priority']) {
    return `${details['old_priority']} \u2192 ${details['new_priority']}`;
  }

  if (details['assigned_to']) {
    return `${t('audit.assigned_to', 'Zugewiesen an:')} ${details['assigned_to']}`;
  }

  return null;
}

// ── Entry Styles ─────────────────────────────────────────────

function getEntryStyles(entry: TimelineEntry): {
  align: string;
  bubble: string;
  dot: string;
  line: string;
} {
  if (entry.type === 'audit') {
    return {
      align: 'items-center',
      bubble: 'bg-neutral-50 border border-neutral-200 text-neutral-600',
      dot: 'bg-neutral-400',
      line: 'border-neutral-200',
    };
  }

  if (entry.type === 'note') {
    return {
      align: 'items-end',
      bubble: 'bg-amber-50 border border-amber-200 text-neutral-900',
      dot: 'bg-amber-500',
      line: 'border-amber-200',
    };
  }

  // Regular message
  if (entry.senderType === 'reporter') {
    return {
      align: 'items-start',
      bubble: 'bg-blue-50 border border-blue-200 text-neutral-900',
      dot: 'bg-blue-500',
      line: 'border-blue-200',
    };
  }

  if (entry.senderType === 'system') {
    return {
      align: 'items-center',
      bubble: 'bg-neutral-50 border border-neutral-200 text-neutral-700',
      dot: 'bg-neutral-400',
      line: 'border-neutral-200',
    };
  }

  // Handler message
  return {
    align: 'items-end',
    bubble: 'bg-primary/5 border border-primary/20 text-neutral-900',
    dot: 'bg-primary',
    line: 'border-primary/20',
  };
}

// ── Timeline Entry Component ─────────────────────────────────

function TimelineEntryCard({ entry }: { entry: TimelineEntry }) {
  const { t, i18n } = useTranslation('cases');
  const styles = getEntryStyles(entry);
  const dateLocale = i18n.language === 'en' ? 'en-US' : 'de-DE';
  const formattedTime = formatTimestamp(entry.timestamp, dateLocale);

  if (entry.type === 'audit') {
    const auditLabel = t('audit_actions.' + (entry.auditAction ?? ''), entry.auditAction ?? '');
    const detail = getAuditDetail(entry.auditDetails ?? null, t);

    return (
      <article
        className={`flex flex-col ${styles.align}`}
        aria-label={`${t('audit.system_event', 'Systemereignis')}: ${auditLabel} um ${formattedTime}`}
      >
        <div
          className={`inline-flex max-w-lg items-center gap-2 rounded-full px-4 py-2 text-xs ${styles.bubble}`}
        >
          {/* Audit Icon */}
          <svg
            className="h-3.5 w-3.5 shrink-0 text-neutral-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <span className="font-medium">
            {auditLabel}
          </span>
          {detail && (
            <span className="text-neutral-500">{detail}</span>
          )}
          <time dateTime={entry.timestamp} className="text-neutral-400">
            {formattedTime}
          </time>
        </div>
      </article>
    );
  }

  const senderLabel = entry.senderType
    ? t('sender.' + entry.senderType, entry.senderType)
    : t('sender.unknown', 'Unbekannt');

  return (
    <article
      className={`flex flex-col ${styles.align}`}
      aria-label={`${entry.type === 'note' ? t('detail.notes.title', 'Interne Notiz') : t('message.label', 'Nachricht')} von ${senderLabel} um ${formattedTime}`}
    >
      <div className={`max-w-[75%] rounded-xl px-4 py-3 ${styles.bubble}`}>
        {/* Header */}
        <div className="mb-1 flex items-center gap-2 text-xs">
          <span className="font-medium text-neutral-700">{senderLabel}</span>
          {entry.type === 'note' && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-200/60 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
              <svg
                className="h-2.5 w-2.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                />
              </svg>
              {t('detail.notes.internal_badge', 'Intern')}
            </span>
          )}
          {!entry.isRead && entry.senderType === 'reporter' && (
            <span
              className="inline-block h-2 w-2 rounded-full bg-primary"
              aria-label={t('message.unread', 'Ungelesen')}
              title={t('message.unread', 'Ungelesen')}
            />
          )}
          <time
            dateTime={entry.timestamp}
            className="ml-auto whitespace-nowrap text-neutral-400"
          >
            {formattedTime}
          </time>
        </div>

        {/* Content */}
        {entry.content && (
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {entry.content}
          </p>
        )}

        {/* Attachments */}
        {entry.attachments && entry.attachments.length > 0 && (
          <div className="mt-2 space-y-1">
            {entry.attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="flex items-center gap-2 rounded-lg bg-white/60 px-2.5 py-1.5 text-xs"
              >
                <svg
                  className="h-4 w-4 shrink-0 text-neutral-500"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                  />
                </svg>
                <span className="min-w-0 flex-1 truncate text-neutral-700">
                  {attachment.original_filename}
                </span>
                <span className="shrink-0 text-neutral-400">
                  {formatFileSize(attachment.file_size)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

// ── Filter Bar ───────────────────────────────────────────────

interface TimelineFilterBarProps {
  filter: TimelineFilter | null;
  onFilterChange: (filter: TimelineFilter | null) => void;
  messageCounts: { messages: number; notes: number; audit: number; total: number };
}

function TimelineFilterBar({
  filter,
  onFilterChange,
  messageCounts,
}: TimelineFilterBarProps) {
  const { t } = useTranslation('cases');
  const filters: { value: TimelineFilter | null; label: string; count: number }[] = [
    { value: null, label: t('list.filter.all', 'Alle'), count: messageCounts.total },
    { value: 'messages', label: t('detail.tabs.messages', 'Nachrichten'), count: messageCounts.messages },
    { value: 'notes', label: t('detail.tabs.notes', 'Notizen'), count: messageCounts.notes },
    { value: 'audit', label: t('detail.tabs.audit', 'Protokoll'), count: messageCounts.audit },
  ];

  return (
    <div className="flex gap-1" role="tablist" aria-label={t('timeline.filter_label', 'Timeline-Filter')}>
      {filters.map((f) => {
        const isActive = filter === f.value;
        return (
          <button
            key={f.value ?? 'all'}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onFilterChange(f.value)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              isActive
                ? 'bg-primary text-white'
                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
            }`}
          >
            {f.label}
            <span className="ml-1.5 opacity-70">({f.count})</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Empty State ──────────────────────────────────────────────

function TimelineEmpty() {
  const { t } = useTranslation('cases');
  return (
    <div className="py-12 text-center text-neutral-500">
      <svg
        className="mx-auto mb-3 h-12 w-12 text-neutral-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>
      <p className="text-sm">{t('timeline.empty', 'Noch keine Einträge in der Timeline.')}</p>
    </div>
  );
}

// ── CaseTimeline Component ───────────────────────────────────

/**
 * Chronological timeline showing all case communication and events.
 *
 * Merges messages, internal notes, and audit trail entries into a single
 * chronological feed. Supports filtering by entry type.
 */
export default function CaseTimeline({
  messages,
  auditTrail,
  showInternalNotes = true,
  filter = null,
}: CaseTimelineProps) {
  const messageCounts = useMemo(() => {
    const publicMessages = messages.filter((m) => !m.is_internal).length;
    const notes = messages.filter((m) => m.is_internal).length;
    return {
      messages: publicMessages,
      notes,
      audit: auditTrail.length,
      total: publicMessages + notes + auditTrail.length,
    };
  }, [messages, auditTrail]);

  const entries = useMemo(
    () => mergeEntries(messages, auditTrail, showInternalNotes, filter),
    [messages, auditTrail, showInternalNotes, filter],
  );

  return (
    <div className="space-y-4">
      {entries.length === 0 ? (
        <TimelineEmpty />
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => (
            <TimelineEntryCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

export { TimelineFilterBar, type TimelineFilter as TimelineFilterType };
