/**
 * Hinweisgebersystem – Audit Log Page.
 *
 * Filterable, paginated audit log viewer with:
 * - Multi-filter bar: action type, actor type, resource type, date range
 * - Paginated table with chronological audit trail
 * - Details column with expandable JSON viewer
 * - CSV export with current filters applied
 *
 * The audit log is an append-only, immutable record of all system
 * actions, required for compliance with HinSchG audit requirements.
 *
 * Requires auditor role. Data is fetched via direct API calls
 * (dedicated audit-log endpoint separate from case audit trail).
 */

import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import apiClient from '@/api/client';
import type { PaginatedResponse, AuditLogEntry } from '@/api/cases';

// ── Types ─────────────────────────────────────────────────────

interface AuditLogParams {
  page?: number;
  page_size?: number;
  action?: string;
  actor_type?: string;
  resource_type?: string;
  date_from?: string;
  date_to?: string;
}

type AuditLogResponse = PaginatedResponse<AuditLogEntry>;

// ── API Functions ─────────────────────────────────────────────

async function getAuditLog(params: AuditLogParams = {}): Promise<AuditLogResponse> {
  const response = await apiClient.get<AuditLogResponse>('/admin/audit-log', {
    params,
  });
  return response.data;
}

async function exportAuditLogCSV(params: Omit<AuditLogParams, 'page' | 'page_size'>): Promise<Blob> {
  const response = await apiClient.get('/admin/audit-log/export', {
    params,
    responseType: 'blob',
  });
  return response.data;
}

// ── Query Keys ────────────────────────────────────────────────

const auditLogKeys = {
  all: ['audit-log'] as const,
  list: (params: AuditLogParams) => [...auditLogKeys.all, 'list', params] as const,
};

// ── Constants ─────────────────────────────────────────────────

const ACTION_OPTIONS = [
  { value: 'case.created', label: 'Fall erstellt' },
  { value: 'case.status_changed', label: 'Status geändert' },
  { value: 'case.assigned', label: 'Fall zugewiesen' },
  { value: 'case.priority_changed', label: 'Priorität geändert' },
  { value: 'case.deleted', label: 'Fall gelöscht' },
  { value: 'message.sent', label: 'Nachricht gesendet' },
  { value: 'message.read', label: 'Nachricht gelesen' },
  { value: 'attachment.uploaded', label: 'Anhang hochgeladen' },
  { value: 'attachment.downloaded', label: 'Anhang heruntergeladen' },
  { value: 'identity.disclosure_requested', label: 'Offenlegung angefordert' },
  { value: 'identity.disclosure_approved', label: 'Offenlegung genehmigt' },
  { value: 'identity.disclosure_rejected', label: 'Offenlegung abgelehnt' },
  { value: 'identity.disclosed', label: 'Identität offengelegt' },
  { value: 'user.created', label: 'Benutzer erstellt' },
  { value: 'user.updated', label: 'Benutzer aktualisiert' },
  { value: 'user.deactivated', label: 'Benutzer deaktiviert' },
  { value: 'user.login', label: 'Benutzer angemeldet' },
  { value: 'user.logout', label: 'Benutzer abgemeldet' },
  { value: 'tenant.created', label: 'Mandant erstellt' },
  { value: 'tenant.updated', label: 'Mandant aktualisiert' },
  { value: 'tenant.deactivated', label: 'Mandant deaktiviert' },
  { value: 'category.created', label: 'Kategorie erstellt' },
  { value: 'category.updated', label: 'Kategorie aktualisiert' },
  { value: 'category.deleted', label: 'Kategorie gelöscht' },
];

const ACTOR_TYPE_OPTIONS = [
  { value: 'user', label: 'Benutzer' },
  { value: 'reporter', label: 'Hinweisgeber' },
  { value: 'system', label: 'System' },
];

const RESOURCE_TYPE_OPTIONS = [
  { value: 'report', label: 'Meldung' },
  { value: 'user', label: 'Benutzer' },
  { value: 'tenant', label: 'Mandant' },
  { value: 'message', label: 'Nachricht' },
  { value: 'attachment', label: 'Anhang' },
  { value: 'disclosure', label: 'Offenlegung' },
  { value: 'category', label: 'Kategorie' },
];

// ── Detail Expander ───────────────────────────────────────────

function DetailsCell({ details }: { details: Record<string, unknown> | null }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!details || Object.keys(details).length === 0) {
    return <span className="text-neutral-400">—</span>;
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="text-xs font-medium text-primary transition-colors hover:text-primary/80"
      >
        {isExpanded ? 'Ausblenden' : 'Details anzeigen'}
      </button>
      {isExpanded && (
        <pre className="mt-2 max-w-xs overflow-x-auto rounded bg-neutral-100 p-2 text-xs text-neutral-700">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── AuditLog Page ─────────────────────────────────────────────

export default function AuditLog() {
  // ── State ───────────────────────────────────────────────────
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [actionFilter, setActionFilter] = useState('');
  const [actorTypeFilter, setActorTypeFilter] = useState('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [isExporting, setIsExporting] = useState(false);

  // ── Query Parameters ────────────────────────────────────────
  const queryParams = useMemo<AuditLogParams>(() => {
    const params: AuditLogParams = { page, page_size: pageSize };
    if (actionFilter) params.action = actionFilter;
    if (actorTypeFilter) params.actor_type = actorTypeFilter;
    if (resourceTypeFilter) params.resource_type = resourceTypeFilter;
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    return params;
  }, [page, pageSize, actionFilter, actorTypeFilter, resourceTypeFilter, dateFrom, dateTo]);

  const { data, isLoading, error } = useQuery<AuditLogResponse, Error>({
    queryKey: auditLogKeys.list(queryParams),
    queryFn: () => getAuditLog(queryParams),
    placeholderData: (prev) => prev,
  });

  // ── Handlers ────────────────────────────────────────────────

  const handleFilterReset = useCallback(() => {
    setActionFilter('');
    setActorTypeFilter('');
    setResourceTypeFilter('');
    setDateFrom('');
    setDateTo('');
    setPage(1);
  }, []);

  const hasActiveFilters = useMemo(
    () =>
      actionFilter !== '' ||
      actorTypeFilter !== '' ||
      resourceTypeFilter !== '' ||
      dateFrom !== '' ||
      dateTo !== '',
    [actionFilter, actorTypeFilter, resourceTypeFilter, dateFrom, dateTo],
  );

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    try {
      const exportParams: Omit<AuditLogParams, 'page' | 'page_size'> = {};
      if (actionFilter) exportParams.action = actionFilter;
      if (actorTypeFilter) exportParams.actor_type = actorTypeFilter;
      if (resourceTypeFilter) exportParams.resource_type = resourceTypeFilter;
      if (dateFrom) exportParams.date_from = dateFrom;
      if (dateTo) exportParams.date_to = dateTo;

      const blob = await exportAuditLogCSV(exportParams);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `audit-log-export-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setIsExporting(false);
    }
  }, [actionFilter, actorTypeFilter, resourceTypeFilter, dateFrom, dateTo]);

  const getActionLabel = useCallback((action: string) => {
    return ACTION_OPTIONS.find((opt) => opt.value === action)?.label ?? action;
  }, []);

  const getActorTypeLabel = useCallback((type: string) => {
    return ACTOR_TYPE_OPTIONS.find((opt) => opt.value === type)?.label ?? type;
  }, []);

  const getResourceTypeLabel = useCallback((type: string) => {
    return RESOURCE_TYPE_OPTIONS.find((opt) => opt.value === type)?.label ?? type;
  }, []);

  const formatTimestamp = useCallback((dateStr: string) => {
    return new Date(dateStr).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }, []);

  // ── Error State ─────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">Fehler beim Laden des Prüfprotokolls</h2>
          <p className="mt-2 text-neutral-600">
            Das Prüfprotokoll konnte nicht geladen werden. Bitte versuchen Sie es später erneut.
          </p>
        </div>
      </div>
    );
  }

  // ── Render ──────────────────────────────────────────────────

  const totalPages = data?.pagination?.total_pages ?? 1;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">Prüfprotokoll</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Alle Systemaktivitäten nachvollziehen
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Page Size */}
          <div className="flex items-center gap-2">
            <label htmlFor="audit-page-size" className="text-sm text-neutral-600">
              Anzeigen:
            </label>
            <select
              id="audit-page-size"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>

          {/* Export Button */}
          <button
            type="button"
            onClick={handleExport}
            disabled={isExporting}
            className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:opacity-50"
          >
            {isExporting ? 'Exportieren...' : 'CSV exportieren'}
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="mb-6 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          {/* Action Filter */}
          <div className="min-w-[200px]">
            <label htmlFor="filter-action" className="mb-1 block text-xs font-medium text-neutral-600">
              Aktion
            </label>
            <select
              id="filter-action"
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle Aktionen</option>
              {ACTION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Actor Type Filter */}
          <div className="min-w-[160px]">
            <label htmlFor="filter-actor-type" className="mb-1 block text-xs font-medium text-neutral-600">
              Akteurtyp
            </label>
            <select
              id="filter-actor-type"
              value={actorTypeFilter}
              onChange={(e) => {
                setActorTypeFilter(e.target.value);
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle Akteurtypen</option>
              {ACTOR_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Resource Type Filter */}
          <div className="min-w-[160px]">
            <label htmlFor="filter-resource-type" className="mb-1 block text-xs font-medium text-neutral-600">
              Ressourcentyp
            </label>
            <select
              id="filter-resource-type"
              value={resourceTypeFilter}
              onChange={(e) => {
                setResourceTypeFilter(e.target.value);
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle Ressourcentypen</option>
              {RESOURCE_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Date From */}
          <div className="min-w-[150px]">
            <label htmlFor="filter-audit-date-from" className="mb-1 block text-xs font-medium text-neutral-600">
              Von
            </label>
            <input
              id="filter-audit-date-from"
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Date To */}
          <div className="min-w-[150px]">
            <label htmlFor="filter-audit-date-to" className="mb-1 block text-xs font-medium text-neutral-600">
              Bis
            </label>
            <input
              id="filter-audit-date-to"
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Reset Button */}
          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleFilterReset}
              className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
            >
              Zurücksetzen
            </button>
          )}
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-neutral-200">
            <thead className="bg-neutral-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Zeitstempel
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Aktion
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Akteurtyp
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Akteur-ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Ressourcentyp
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Ressourcen-ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Details
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  IP-Adresse
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {isLoading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 8 }).map((__, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 w-20 animate-pulse rounded bg-neutral-200" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !data?.items?.length ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-neutral-500">
                    Keine Protokolleinträge gefunden.
                  </td>
                </tr>
              ) : (
                data.items.map((entry) => (
                  <tr key={entry.id} className="transition-colors hover:bg-neutral-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {formatTimestamp(entry.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium text-neutral-700">
                        {getActionLabel(entry.action)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {getActorTypeLabel(entry.actor_type)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-500">
                      {entry.actor_id ? (
                        <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs">
                          {entry.actor_id.slice(0, 8)}...
                        </code>
                      ) : (
                        <span className="text-neutral-400">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {getResourceTypeLabel(entry.resource_type)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-500">
                      <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs">
                        {entry.resource_id.slice(0, 8)}...
                      </code>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <DetailsCell details={entry.details} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-500">
                      {entry.ip_address ?? <span className="text-neutral-400">—</span>}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data?.pagination && data.pagination.total_pages > 1 && (
          <div className="flex items-center justify-between border-t border-neutral-200 bg-white px-4 py-3">
            <p className="text-sm text-neutral-600">
              Seite {data.pagination.page} von {data.pagination.total_pages} ({data.pagination.total}{' '}
              Einträge)
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:opacity-50"
              >
                Zurück
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:opacity-50"
              >
                Weiter
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
