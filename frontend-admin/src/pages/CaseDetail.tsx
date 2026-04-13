/**
 * Hinweisgebersystem – Admin Case Detail Page.
 *
 * Full case view with all metadata and a tabbed interface:
 * - **Nachrichten**: Communication timeline with messages and notes
 * - **Notizen**: Internal notes visible only to handlers
 * - **Dateien**: Attached files from messages
 * - **Protokoll**: Audit trail of all case events
 *
 * Additional features:
 * - Status workflow indicator with transition controls
 * - Priority, assignment, and category editing
 * - Message composer for replying to the reporter
 * - Internal note editor (handler-to-handler)
 * - Custodian identity disclosure modal (4-eyes principle)
 * - Deadline highlighting for confirmation and feedback
 * - Back navigation to case list
 *
 * Data is fetched via TanStack Query hooks with 15-second auto-refresh
 * for live message updates.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import { useAuth } from '@/hooks/useAuth';
import {
  useCaseDetail,
  useUpdateCase,
  useSendMessage,
  useCreateNote,
  useReportDisclosures,
  useRequestDisclosure,
  useApproveDisclosure,
  useRevealIdentity,
  useLabels,
  useAssignLabel,
  useRemoveLabel,
} from '@/hooks/useCases';
import CaseTimeline from '@/components/CaseTimeline';
import StatusWorkflow from '@/components/StatusWorkflow';
import InternalNote from '@/components/InternalNote';
import CustodianDialog from '@/components/CustodianDialog';
import LabelBadge from '@/components/LabelBadge';
import type {
  ReportStatus,
  Priority,
  AttachmentSummary,
  IdentityRevealResponse,
} from '@/api/cases';

// ── Tab Definitions ──────────────────────────────────────────

type TabId = 'messages' | 'notes' | 'files' | 'audit';

interface TabDef {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  {
    id: 'messages',
    label: 'detail.tabs.messages',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
  },
  {
    id: 'notes',
    label: 'detail.tabs.notes',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
  },
  {
    id: 'files',
    label: 'detail.tabs.files',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
      </svg>
    ),
  },
  {
    id: 'audit',
    label: 'detail.tabs.audit',
    icon: (
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    ),
  },
];

// ── Label Maps ───────────────────────────────────────────────

const PRIORITY_COLORS: Record<Priority, string> = {
  low: 'bg-neutral-100 text-neutral-700',
  medium: 'bg-blue-100 text-blue-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
};

// ── Date Formatting ──────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return '\u2013';
  try {
    return new Date(iso).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '\u2013';
  try {
    return new Date(iso).toLocaleString('de-DE', {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Deadline Badge ───────────────────────────────────────────

function DeadlineBadge({
  label,
  deadline,
  sentAt,
  isOverdue,
}: {
  label: string;
  deadline: string | null;
  sentAt: string | null;
  isOverdue: boolean;
}) {
  const { t } = useTranslation('cases');
  if (!deadline) return null;

  const daysUntil = Math.ceil(
    (new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  );

  let badgeClass = 'bg-neutral-100 text-neutral-700';
  let statusText = formatDate(deadline);

  if (sentAt) {
    badgeClass = 'bg-green-100 text-green-800';
    statusText = `${t('detail.deadlines.completed_at', 'Erledigt am')} ${formatDate(sentAt)}`;
  } else if (isOverdue) {
    badgeClass = 'bg-red-100 text-red-800';
    statusText = `${formatDate(deadline)} (${Math.abs(daysUntil)}d ${t('detail.deadlines.overdue', 'überfällig')})`;
  } else if (daysUntil <= 7) {
    badgeClass = 'bg-yellow-100 text-yellow-800';
    statusText = `${formatDate(deadline)} (${daysUntil}d)`;
  }

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-neutral-500">{label}</span>
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
        {statusText}
      </span>
    </div>
  );
}

// ── Message Composer ─────────────────────────────────────────

interface MessageComposerProps {
  onSend: (content: string) => void;
  isSending: boolean;
}

function MessageComposer({ onSend, isSending }: MessageComposerProps) {
  const { t } = useTranslation('cases');
  const [message, setMessage] = useState('');
  const trimmedMessage = message.trim();
  const canSend = trimmedMessage.length > 0 && !isSending;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSend) return;
      onSend(trimmedMessage);
      setMessage('');
    },
    [canSend, trimmedMessage, onSend],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (canSend) {
          onSend(trimmedMessage);
          setMessage('');
        }
      }
    },
    [canSend, trimmedMessage, onSend],
  );

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-neutral-200 bg-white p-4">
      <label htmlFor="reply-message" className="mb-2 block text-sm font-medium text-neutral-700">
        {t('detail.messages.reply_label', 'Antwort an Hinweisgeber')}
      </label>
      <textarea
        id="reply-message"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('detail.messages.compose_placeholder', 'Nachricht verfassen… (sichtbar im anonymen Postfach)')}
        rows={3}
        disabled={isSending}
        className="w-full resize-none rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-neutral-400">{t('detail.messages.keyboard_hint', 'Ctrl+Enter zum Absenden')}</span>
        <button
          type="submit"
          disabled={!canSend}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSending ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              {t('detail.messages.sending', 'Wird gesendet…')}
            </>
          ) : (
            <>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
              {t('detail.messages.send', 'Senden')}
            </>
          )}
        </button>
      </div>
    </form>
  );
}

// ── File List ────────────────────────────────────────────────

function FileList({ attachments }: { attachments: AttachmentSummary[] }) {
  const { t } = useTranslation('cases');
  if (attachments.length === 0) {
    return (
      <div className="py-12 text-center text-neutral-500">
        <svg
          className="mx-auto mb-3 h-12 w-12 text-neutral-300"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
        <p className="text-sm">{t('detail.files.empty', 'Keine Dateien zu diesem Fall.')}</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
      {attachments.map((file) => (
        <div
          key={file.id}
          className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-neutral-50"
        >
          {/* File type icon */}
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-neutral-100">
            <svg
              className="h-5 w-5 text-neutral-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          </div>

          {/* File info */}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-neutral-900">
              {file.original_filename}
            </p>
            <p className="text-xs text-neutral-500">
              {file.content_type} &middot; {formatFileSize(file.file_size)} &middot;{' '}
              {formatDate(file.created_at)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Metadata Panel ───────────────────────────────────────────

function MetadataRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <dt className="text-xs font-medium text-neutral-500">{label}</dt>
      <dd className="text-sm text-neutral-900">{children}</dd>
    </div>
  );
}

// ── Loading Skeleton ─────────────────────────────────────────

function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8" role="status" aria-label="Falldetails werden geladen…">
      <div className="animate-pulse space-y-6">
        <div className="h-8 w-48 rounded bg-neutral-200" />
        <div className="h-24 rounded-lg bg-neutral-200" />
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 h-96 rounded-lg bg-neutral-200" />
          <div className="h-96 rounded-lg bg-neutral-200" />
        </div>
      </div>
    </div>
  );
}

// ── CaseDetail Page ──────────────────────────────────────────

/**
 * Full case detail page with tabbed content and status workflow.
 *
 * Fetches the case detail (including messages and audit trail) by ID
 * from the URL parameter. Provides controls for status changes,
 * messaging, internal notes, and custodian identity disclosure.
 */
export default function CaseDetail() {
  const { t } = useTranslation('cases');
  const { caseId } = useParams<{ caseId: string }>();
  const { user, hasRole } = useAuth();

  // ── State ──────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<TabId>('messages');
  const [showCustodianDialog, setShowCustodianDialog] = useState(false);
  const [revealedIdentity, setRevealedIdentity] = useState<IdentityRevealResponse | null>(null);

  // ── Data Fetching ──────────────────────────────────────────
  const {
    data: caseDetail,
    isLoading,
    error,
  } = useCaseDetail({ caseId: caseId ?? '' });

  const { data: disclosures = [] } = useReportDisclosures(
    caseId ?? '',
    !!caseId && (caseDetail?.is_anonymous ?? false),
  );

  // ── Mutations ──────────────────────────────────────────────
  const updateCase = useUpdateCase();
  const sendMessageMutation = useSendMessage();
  const createNoteMutation = useCreateNote();
  const requestDisclosureMutation = useRequestDisclosure();
  const approveDisclosureMutation = useApproveDisclosure();
  const revealIdentityMutation = useRevealIdentity();
  const assignLabelMutation = useAssignLabel();
  const removeLabelMutation = useRemoveLabel();

  // ── Labels ────────────────────────────────────────────────
  const { data: labelsData } = useLabels({
    params: { active_only: true, page_size: 100 },
  });

  const availableLabels = useMemo(() => {
    if (!labelsData?.items || !caseDetail) return [];
    const assignedIds = new Set((caseDetail.labels ?? []).map((l) => l.id));
    return labelsData.items.filter((l) => !assignedIds.has(l.id));
  }, [labelsData, caseDetail]);

  // ── Derived Data ───────────────────────────────────────────

  const allAttachments = useMemo<AttachmentSummary[]>(() => {
    if (!caseDetail?.messages) return [];
    return caseDetail.messages.flatMap((msg) => msg.attachments);
  }, [caseDetail?.messages]);

  const publicMessages = useMemo(() => {
    if (!caseDetail?.messages) return [];
    return caseDetail.messages.filter((m) => !m.is_internal);
  }, [caseDetail?.messages]);

  const internalNotes = useMemo(() => {
    if (!caseDetail?.messages) return [];
    return caseDetail.messages.filter((m) => m.is_internal);
  }, [caseDetail?.messages]);

  // ── Permission Checks ─────────────────────────────────────
  const canEdit = hasRole('handler');
  const isCustodian = user?.is_custodian ?? false;

  // ── Handlers ───────────────────────────────────────────────

  const handleStatusChange = useCallback(
    (newStatus: ReportStatus) => {
      if (!caseDetail || !caseId) return;
      updateCase.mutate({
        caseId,
        data: { status: newStatus, version: caseDetail.version },
      });
    },
    [caseDetail, caseId, updateCase],
  );

  const handleSendMessage = useCallback(
    (content: string) => {
      if (!caseId) return;
      sendMessageMutation.mutate({ caseId, content });
    },
    [caseId, sendMessageMutation],
  );

  const handleCreateNote = useCallback(
    (content: string) => {
      if (!caseId) return;
      createNoteMutation.mutate({ caseId, content });
    },
    [caseId, createNoteMutation],
  );

  const handleRequestDisclosure = useCallback(
    (reason: string) => {
      if (!caseId) return;
      requestDisclosureMutation.mutate({ report_id: caseId, reason });
    },
    [caseId, requestDisclosureMutation],
  );

  const handleDecideDisclosure = useCallback(
    (disclosureId: string, approved: boolean, decisionReason?: string) => {
      approveDisclosureMutation.mutate({
        disclosureId,
        data: { approved, decision_reason: decisionReason },
      });
    },
    [approveDisclosureMutation],
  );

  const handleRevealIdentity = useCallback(
    (disclosureId: string) => {
      revealIdentityMutation.mutate(disclosureId, {
        onSuccess: (data) => {
          setRevealedIdentity(data);
        },
      });
    },
    [revealIdentityMutation],
  );

  const handleAssignLabel = useCallback(
    (labelId: string) => {
      if (!caseId || !labelId) return;
      assignLabelMutation.mutate({ caseId, labelId });
    },
    [caseId, assignLabelMutation],
  );

  const handleRemoveLabel = useCallback(
    (labelId: string) => {
      if (!caseId) return;
      removeLabelMutation.mutate({ caseId, labelId });
    },
    [caseId, removeLabelMutation],
  );

  // ── Tab Counts ─────────────────────────────────────────────

  const tabCounts: Record<TabId, number> = useMemo(
    () => ({
      messages: publicMessages.length,
      notes: internalNotes.length,
      files: allAttachments.length,
      audit: caseDetail?.audit_trail?.length ?? 0,
    }),
    [publicMessages, internalNotes, allAttachments, caseDetail?.audit_trail],
  );

  // ── Error State ────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">{t('detail.error.title', 'Fehler beim Laden des Falls')}</h2>
          <p className="mt-2 text-neutral-600">
            {t('detail.error.message', 'Die Falldetails konnten nicht geladen werden. Bitte versuchen Sie es später erneut.')}
          </p>
          <Link to="/cases" className="mt-4 inline-block text-sm font-medium text-primary hover:text-primary-dark">
            &larr; {t('detail.back', 'Zurück zur Übersicht')}
          </Link>
        </div>
      </div>
    );
  }

  // ── Loading State ──────────────────────────────────────────

  if (isLoading || !caseDetail) {
    return <DetailSkeleton />;
  }

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Breadcrumb Navigation */}
      <nav className="mb-6" aria-label="Breadcrumb">
        <Link
          to="/cases"
          className="inline-flex items-center gap-1 text-sm font-medium text-primary transition-colors hover:text-primary-dark"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          {t('detail.back', 'Zurück zur Übersicht')}
        </Link>
      </nav>

      {/* Page Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-neutral-900">
              Fall {caseDetail.case_number}
            </h1>
            {caseDetail.is_anonymous && (
              <span className="inline-flex items-center gap-1 rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium text-neutral-700">
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                {t('detail.metadata.anonymous', 'Anonym')}
              </span>
            )}
            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${PRIORITY_COLORS[caseDetail.priority]}`}>
              {t('common:priority.' + caseDetail.priority)}
            </span>
          </div>
          <p className="mt-1 text-sm text-neutral-500">
            {t('common:channel.' + caseDetail.channel)} &middot; {t('detail.metadata.created_at', 'Erstellt am')} {formatDate(caseDetail.created_at)}
            {caseDetail.subject && ` &middot; ${caseDetail.subject}`}
          </p>
        </div>

        {/* Identity disclosure button for anonymous cases */}
        {caseDetail.is_anonymous && canEdit && (
          <button
            type="button"
            onClick={() => setShowCustodianDialog(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger/10"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            {t('detail.request_identity', 'Identität anfragen')}
          </button>
        )}
      </div>

      {/* Status Workflow */}
      <div className="mb-6">
        <StatusWorkflow
          currentStatus={caseDetail.status}
          onStatusChange={handleStatusChange}
          isUpdating={updateCase.isPending}
          canEdit={canEdit}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: Tabbed Content (2/3 width) */}
        <div className="lg:col-span-2">
          {/* Tab Bar */}
          <div className="mb-4 flex border-b border-neutral-200" role="tablist" aria-label="Falldetail-Tabs">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`tabpanel-${tab.id}`}
                  id={`tab-${tab.id}`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'border-transparent text-neutral-500 hover:border-neutral-300 hover:text-neutral-700'
                  }`}
                >
                  {tab.icon}
                  {t(tab.label)}
                  {tabCounts[tab.id] > 0 && (
                    <span
                      className={`ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-xs ${
                        isActive
                          ? 'bg-primary/10 text-primary'
                          : 'bg-neutral-100 text-neutral-500'
                      }`}
                    >
                      {tabCounts[tab.id]}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Tab Panels */}
          <div
            id={`tabpanel-${activeTab}`}
            role="tabpanel"
            aria-labelledby={`tab-${activeTab}`}
          >
            {/* Messages Tab */}
            {activeTab === 'messages' && (
              <div className="space-y-4">
                <CaseTimeline
                  messages={caseDetail.messages}
                  auditTrail={[]}
                  showInternalNotes={false}
                  filter="messages"
                />
                {canEdit && (
                  <MessageComposer
                    onSend={handleSendMessage}
                    isSending={sendMessageMutation.isPending}
                  />
                )}
              </div>
            )}

            {/* Notes Tab */}
            {activeTab === 'notes' && (
              <div className="space-y-4">
                <CaseTimeline
                  messages={caseDetail.messages}
                  auditTrail={[]}
                  showInternalNotes={true}
                  filter="notes"
                />
                {canEdit && (
                  <InternalNote
                    onSubmit={handleCreateNote}
                    isSubmitting={createNoteMutation.isPending}
                  />
                )}
              </div>
            )}

            {/* Files Tab */}
            {activeTab === 'files' && <FileList attachments={allAttachments} />}

            {/* Audit Tab */}
            {activeTab === 'audit' && (
              <CaseTimeline
                messages={[]}
                auditTrail={caseDetail.audit_trail}
                showInternalNotes={false}
                filter="audit"
              />
            )}
          </div>
        </div>

        {/* Right: Metadata Sidebar (1/3 width) */}
        <aside className="space-y-6">
          {/* Case Metadata */}
          <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
              {t('detail.case_details', 'Falldetails')}
            </h3>
            <dl className="divide-y divide-neutral-100">
              <MetadataRow label={t('detail.case_number', 'Fallnummer')}>{caseDetail.case_number}</MetadataRow>
              <MetadataRow label={t('detail.metadata.status', 'Status')}>
                <span className="font-medium">
                  {t('common:status.' + caseDetail.status)}
                </span>
              </MetadataRow>
              <MetadataRow label={t('detail.metadata.priority', 'Priorität')}>
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY_COLORS[caseDetail.priority]}`}>
                  {t('common:priority.' + caseDetail.priority)}
                </span>
              </MetadataRow>
              <MetadataRow label={t('detail.metadata.channel', 'Kanal')}>{t('common:channel.' + caseDetail.channel)}</MetadataRow>
              <MetadataRow label={t('detail.metadata.category', 'Kategorie')}>{caseDetail.category ?? '\u2013'}</MetadataRow>
              <MetadataRow label={t('detail.metadata.language', 'Sprache')}>{caseDetail.language.toUpperCase()}</MetadataRow>
              <MetadataRow label={t('detail.metadata.anonymous', 'Anonym')}>
                {caseDetail.is_anonymous ? t('common:boolean.yes', 'Ja') : t('common:boolean.no', 'Nein')}
              </MetadataRow>
              <MetadataRow label={t('detail.metadata.created_at', 'Erstellt am')}>{formatDateTime(caseDetail.created_at)}</MetadataRow>
              <MetadataRow label={t('detail.metadata.updated_at', 'Aktualisiert am')}>{formatDateTime(caseDetail.updated_at)}</MetadataRow>
              <MetadataRow label={t('detail.metadata.assigned_to', 'Zugewiesen an')}>{caseDetail.assigned_to ?? '\u2013'}</MetadataRow>
              {caseDetail.organization && (
                <MetadataRow label={t('detail.lksg.organization', 'Organisation')}>{caseDetail.organization}</MetadataRow>
              )}
              {caseDetail.country && (
                <MetadataRow label={t('detail.lksg.country', 'Land')}>{caseDetail.country}</MetadataRow>
              )}
            </dl>
          </div>

          {/* Labels */}
          <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
              {t('detail.labels.title', 'Labels')}
            </h3>

            {/* Assigned Labels */}
            {caseDetail.labels && caseDetail.labels.length > 0 ? (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {caseDetail.labels.map((label) => (
                  <LabelBadge
                    key={label.id}
                    name={label.name}
                    color={label.color}
                    size="md"
                    onRemove={
                      canEdit
                        ? () => handleRemoveLabel(label.id)
                        : undefined
                    }
                  />
                ))}
              </div>
            ) : (
              <p className="mb-3 text-xs text-neutral-400">
                {t('detail.labels.none', 'Keine Labels zugewiesen.')}
              </p>
            )}

            {/* Add Label Dropdown */}
            {canEdit && availableLabels.length > 0 && (
              <div>
                <label
                  htmlFor="add-label"
                  className="sr-only"
                >
                  {t('detail.labels.add', 'Label hinzufügen')}
                </label>
                <select
                  id="add-label"
                  value=""
                  onChange={(e) => handleAssignLabel(e.target.value)}
                  disabled={assignLabelMutation.isPending}
                  className="w-full rounded-md border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="" disabled>
                    {assignLabelMutation.isPending
                      ? t('detail.labels.adding', 'Wird hinzugefügt…')
                      : t('detail.labels.add_placeholder', '+ Label hinzufügen…')}
                  </option>
                  {availableLabels.map((label) => (
                    <option key={label.id} value={label.id}>
                      {label.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Reporter Info (non-anonymous only) */}
          {!caseDetail.is_anonymous && (
            <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
                {t('detail.reporter.title', 'Hinweisgeber')}
              </h3>
              <dl className="divide-y divide-neutral-100">
                <MetadataRow label={t('detail.reporter.name', 'Name')}>{caseDetail.reporter_name ?? '\u2013'}</MetadataRow>
                <MetadataRow label={t('detail.reporter.email', 'E-Mail')}>{caseDetail.reporter_email ?? '\u2013'}</MetadataRow>
                <MetadataRow label={t('detail.reporter.phone', 'Telefon')}>{caseDetail.reporter_phone ?? '\u2013'}</MetadataRow>
                {caseDetail.reporter_relationship && (
                  <MetadataRow label={t('detail.reporter.relationship', 'Beziehung')}>{caseDetail.reporter_relationship}</MetadataRow>
                )}
              </dl>
            </div>
          )}

          {/* LkSG-specific fields */}
          {caseDetail.channel === 'lksg' && (
            <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
                {t('detail.lksg.title', 'LkSG-Daten')}
              </h3>
              <dl className="divide-y divide-neutral-100">
                {caseDetail.supply_chain_tier && (
                  <MetadataRow label={t('detail.lksg.supply_chain_tier', 'Lieferkettenstufe')}>{caseDetail.supply_chain_tier}</MetadataRow>
                )}
                {caseDetail.lksg_category && (
                  <MetadataRow label={t('detail.lksg.category', 'LkSG-Kategorie')}>{caseDetail.lksg_category}</MetadataRow>
                )}
              </dl>
            </div>
          )}

          {/* Deadlines */}
          <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
              {t('detail.deadlines.title', 'Fristen')}
            </h3>
            <div className="space-y-2">
              <DeadlineBadge
                label={t('detail.deadlines.confirmation', 'Eingangsbestätigung')}
                deadline={caseDetail.confirmation_deadline}
                sentAt={caseDetail.confirmation_sent_at}
                isOverdue={caseDetail.is_overdue_confirmation}
              />
              <DeadlineBadge
                label={t('detail.deadlines.feedback', 'Rückmeldung')}
                deadline={caseDetail.feedback_deadline}
                sentAt={caseDetail.feedback_sent_at}
                isOverdue={caseDetail.is_overdue_feedback}
              />
              {caseDetail.retention_until && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-neutral-500">{t('detail.deadlines.retention', 'Aufbewahrung bis')}</span>
                  <span className="text-xs font-medium text-neutral-700">
                    {formatDate(caseDetail.retention_until)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Related Cases */}
          {caseDetail.related_case_numbers &&
            caseDetail.related_case_numbers.length > 0 && (
              <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
                  {t('detail.metadata.related_cases', 'Verknüpfte Fälle')}
                </h3>
                <div className="space-y-1">
                  {caseDetail.related_case_numbers.map((caseNum) => (
                    <span
                      key={caseNum}
                      className="mr-2 inline-flex rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium text-primary"
                    >
                      {caseNum}
                    </span>
                  ))}
                </div>
              </div>
            )}

          {/* Description */}
          {caseDetail.description && (
            <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-600">
                {t('detail.metadata.description', 'Beschreibung')}
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-700">
                {caseDetail.description}
              </p>
            </div>
          )}
        </aside>
      </div>

      {/* Custodian Identity Disclosure Dialog */}
      <CustodianDialog
        isOpen={showCustodianDialog}
        onClose={() => setShowCustodianDialog(false)}
        reportId={caseId ?? ''}
        isAnonymous={caseDetail.is_anonymous}
        existingDisclosures={disclosures}
        isCustodian={isCustodian}
        onRequestDisclosure={handleRequestDisclosure}
        onDecideDisclosure={handleDecideDisclosure}
        onRevealIdentity={handleRevealIdentity}
        revealedIdentity={revealedIdentity}
        isRequesting={requestDisclosureMutation.isPending}
        isDeciding={approveDisclosureMutation.isPending}
        isRevealing={revealIdentityMutation.isPending}
      />
    </div>
  );
}
