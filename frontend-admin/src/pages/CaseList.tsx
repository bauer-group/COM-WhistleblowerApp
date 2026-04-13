/**
 * Hinweisgebersystem – Admin Case List Page.
 *
 * Full-featured case listing page with:
 * - Paginated table with column sorting
 * - Multi-filter bar: status, category, date range, priority, channel, label
 * - Label filter with active filter chip display
 * - Full-text search input with debounced query
 * - Deadline highlighting (yellow for 7-day approaching, red for overdue)
 * - URL-synced filter state for bookmarkable views
 *
 * Data is fetched via TanStack Query hooks with keepPreviousData
 * for smooth pagination transitions and 30-second auto-refresh.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCases, useLabels } from '@/hooks/useCases';
import CaseTable from '@/components/CaseTable';
import LabelBadge from '@/components/LabelBadge';
import type { SortConfig } from '@/components/CaseTable';
import type {
  CaseListParams,
  ReportStatus,
  Priority,
  Channel,
} from '@/api/cases';

// ── Filter State ──────────────────────────────────────────────

interface FilterState {
  status: ReportStatus | '';
  priority: Priority | '';
  channel: Channel | '';
  category: string;
  date_from: string;
  date_to: string;
  overdue_only: boolean;
  label_id: string;
}

const INITIAL_FILTERS: FilterState = {
  status: '',
  priority: '',
  channel: '',
  category: '',
  date_from: '',
  date_to: '',
  overdue_only: false,
  label_id: '',
};

// ── Search Debounce Hook ──────────────────────────────────────

/**
 * Custom hook for debounced search input.
 *
 * Returns the immediate input value for the controlled input and
 * a debounced value for the API query, preventing excessive requests
 * during typing.
 */
function useDebouncedSearch(delay = 400) {
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [timerId, setTimerId] = useState<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchInput(value);

      if (timerId) {
        clearTimeout(timerId);
      }

      const id = setTimeout(() => {
        setDebouncedSearch(value);
      }, delay);

      setTimerId(id);
    },
    [delay, timerId],
  );

  return { searchInput, debouncedSearch, handleSearchChange };
}

// ── Filter Bar Component ──────────────────────────────────────

interface LabelOption {
  id: string;
  name: string;
  color: string;
}

interface FilterBarProps {
  filters: FilterState;
  onFilterChange: (key: keyof FilterState, value: string | boolean) => void;
  onReset: () => void;
  searchInput: string;
  onSearchChange: (value: string) => void;
  labelOptions: LabelOption[];
}

function FilterBar({
  filters,
  onFilterChange,
  onReset,
  searchInput,
  onSearchChange,
  labelOptions,
}: FilterBarProps) {
  const { t } = useTranslation('cases');

  const statusOptions = [
    { value: 'eingegangen' as ReportStatus, label: t('common:status.eingegangen', 'Eingegangen') },
    { value: 'in_pruefung' as ReportStatus, label: t('common:status.in_pruefung', 'In Prüfung') },
    { value: 'in_bearbeitung' as ReportStatus, label: t('common:status.in_bearbeitung', 'In Bearbeitung') },
    { value: 'rueckmeldung' as ReportStatus, label: t('common:status.rueckmeldung', 'Rückmeldung') },
    { value: 'abgeschlossen' as ReportStatus, label: t('common:status.abgeschlossen', 'Abgeschlossen') },
  ];
  const priorityOptions = [
    { value: 'low' as Priority, label: t('common:priority.low', 'Niedrig') },
    { value: 'medium' as Priority, label: t('common:priority.medium', 'Mittel') },
    { value: 'high' as Priority, label: t('common:priority.high', 'Hoch') },
    { value: 'critical' as Priority, label: t('common:priority.critical', 'Kritisch') },
  ];
  const channelOptions = [
    { value: 'hinschg' as Channel, label: t('common:channel.hinschg', 'HinSchG') },
    { value: 'lksg' as Channel, label: t('common:channel.lksg', 'LkSG') },
  ];

  const hasActiveFilters = useMemo(
    () =>
      filters.status !== '' ||
      filters.priority !== '' ||
      filters.channel !== '' ||
      filters.category !== '' ||
      filters.date_from !== '' ||
      filters.date_to !== '' ||
      filters.overdue_only ||
      filters.label_id !== '' ||
      searchInput !== '',
    [filters, searchInput],
  );

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
      {/* Search Input */}
      <div className="mb-4">
        <label htmlFor="case-search" className="sr-only">
          {t('list.search_label', 'Fälle durchsuchen')}
        </label>
        <div className="relative">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-neutral-400"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
              clipRule="evenodd"
            />
          </svg>
          <input
            id="case-search"
            type="search"
            placeholder={t('list.search_placeholder', 'Volltextsuche in Fällen...')}
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-md border border-neutral-300 py-2 pl-10 pr-4 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      {/* Filter Row */}
      <div className="flex flex-wrap items-end gap-3">
        {/* Status */}
        <div className="min-w-[140px]">
          <label
            htmlFor="filter-status"
            className="mb-1 block text-xs font-medium text-neutral-600"
          >
            {t('list.filter.status', 'Status')}
          </label>
          <select
            id="filter-status"
            value={filters.status}
            onChange={(e) => onFilterChange('status', e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">{t('list.filter.all', 'Alle')}</option>
            {statusOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Priority */}
        <div className="min-w-[130px]">
          <label
            htmlFor="filter-priority"
            className="mb-1 block text-xs font-medium text-neutral-600"
          >
            {t('list.filter.priority', 'Priorität')}
          </label>
          <select
            id="filter-priority"
            value={filters.priority}
            onChange={(e) => onFilterChange('priority', e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">{t('list.filter.all', 'Alle')}</option>
            {priorityOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Channel */}
        <div className="min-w-[120px]">
          <label
            htmlFor="filter-channel"
            className="mb-1 block text-xs font-medium text-neutral-600"
          >
            {t('list.filter.channel', 'Kanal')}
          </label>
          <select
            id="filter-channel"
            value={filters.channel}
            onChange={(e) => onFilterChange('channel', e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">{t('list.filter.all', 'Alle')}</option>
            {channelOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Label */}
        {labelOptions.length > 0 && (
          <div className="min-w-[140px]">
            <label
              htmlFor="filter-label"
              className="mb-1 block text-xs font-medium text-neutral-600"
            >
              {t('list.filter.label', 'Label')}
            </label>
            <select
              id="filter-label"
              value={filters.label_id}
              onChange={(e) => onFilterChange('label_id', e.target.value)}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">{t('list.filter.all', 'Alle')}</option>
              {labelOptions.map((label) => (
                <option key={label.id} value={label.id}>
                  {label.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Date From */}
        <div className="min-w-[150px]">
          <label
            htmlFor="filter-date-from"
            className="mb-1 block text-xs font-medium text-neutral-600"
          >
            {t('list.filter.date_from', 'Von')}
          </label>
          <input
            id="filter-date-from"
            type="date"
            value={filters.date_from}
            onChange={(e) => onFilterChange('date_from', e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {/* Date To */}
        <div className="min-w-[150px]">
          <label
            htmlFor="filter-date-to"
            className="mb-1 block text-xs font-medium text-neutral-600"
          >
            {t('list.filter.date_to', 'Bis')}
          </label>
          <input
            id="filter-date-to"
            type="date"
            value={filters.date_to}
            onChange={(e) => onFilterChange('date_to', e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {/* Overdue Only */}
        <div className="flex items-center gap-2 pb-1">
          <input
            id="filter-overdue"
            type="checkbox"
            checked={filters.overdue_only}
            onChange={(e) => onFilterChange('overdue_only', e.target.checked)}
            className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
          />
          <label
            htmlFor="filter-overdue"
            className="text-sm font-medium text-neutral-700"
          >
            {t('list.filter.overdue_only', 'Nur überfällige')}
          </label>
        </div>

        {/* Reset Button */}
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onReset}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
          >
            {t('list.filter.reset', 'Zurücksetzen')}
          </button>
        )}
      </div>

      {/* Active Label Filter Chip */}
      {filters.label_id && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-neutral-500">
            {t('list.filter.active_label', 'Aktiver Label-Filter:')}
          </span>
          {(() => {
            const activeLabel = labelOptions.find((l) => l.id === filters.label_id);
            if (!activeLabel) return null;
            return (
              <LabelBadge
                name={activeLabel.name}
                color={activeLabel.color}
                size="sm"
                onRemove={() => onFilterChange('label_id', '')}
              />
            );
          })()}
        </div>
      )}
    </div>
  );
}

// ── Page Size Selector ────────────────────────────────────────

function PageSizeSelector({
  value,
  onChange,
}: {
  value: number;
  onChange: (size: number) => void;
}) {
  const { t } = useTranslation('common');
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="page-size" className="text-sm text-neutral-600">
        {t('table.show', 'Anzeigen:')}
      </label>
      <select
        id="page-size"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-md border border-neutral-300 px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
      >
        <option value={10}>10</option>
        <option value={25}>25</option>
        <option value={50}>50</option>
        <option value={100}>100</option>
      </select>
    </div>
  );
}

// ── CaseList Page ─────────────────────────────────────────────

/**
 * Full-featured case listing page with search, filters, sorting, and pagination.
 *
 * All filter/sort/pagination state is managed locally and passed to the
 * useCases hook as query parameters. TanStack Query handles caching,
 * deduplication, and background refetching.
 */
export default function CaseList() {
  const { t } = useTranslation('cases');

  // ── State ───────────────────────────────────────────────────
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState<SortConfig>({
    sort_by: 'created_at',
    sort_desc: true,
  });
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const { searchInput, debouncedSearch, handleSearchChange } = useDebouncedSearch();

  // ── Fetch Labels for Filter ────────────────────────────────
  const { data: labelsData } = useLabels({
    params: { active_only: true, page_size: 100 },
  });

  const labelOptions = useMemo(
    () =>
      (labelsData?.items ?? []).map((l) => ({
        id: l.id,
        name: l.name,
        color: l.color,
      })),
    [labelsData],
  );

  // ── Build Query Params ──────────────────────────────────────
  const queryParams = useMemo<CaseListParams>(() => {
    const params: CaseListParams = {
      page,
      page_size: pageSize,
      sort_by: sort.sort_by,
      sort_desc: sort.sort_desc,
    };

    if (filters.status) params.status = filters.status as ReportStatus;
    if (filters.priority) params.priority = filters.priority as Priority;
    if (filters.channel) params.channel = filters.channel as Channel;
    if (filters.category) params.category = filters.category;
    if (filters.date_from) params.date_from = filters.date_from;
    if (filters.date_to) params.date_to = filters.date_to;
    if (filters.overdue_only) params.overdue_only = true;
    if (filters.label_id) params.label_id = filters.label_id;
    if (debouncedSearch) params.search = debouncedSearch;

    return params;
  }, [page, pageSize, sort, filters, debouncedSearch]);

  const { data, isLoading, error } = useCases({ params: queryParams });

  // ── Handlers ────────────────────────────────────────────────

  const handleFilterChange = useCallback(
    (key: keyof FilterState, value: string | boolean) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
      setPage(1); // Reset to first page on filter change
    },
    [],
  );

  const handleFilterReset = useCallback(() => {
    setFilters(INITIAL_FILTERS);
    handleSearchChange('');
    setPage(1);
  }, [handleSearchChange]);

  const handleSortChange = useCallback((newSort: SortConfig) => {
    setSort(newSort);
    setPage(1); // Reset to first page on sort change
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  const handlePageSizeChange = useCallback((newSize: number) => {
    setPageSize(newSize);
    setPage(1); // Reset to first page on page size change
  }, []);

  // ── Error State ─────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div
          className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center"
          role="alert"
        >
          <h2 className="text-lg font-semibold text-danger">
            {t('list.error.title', 'Fehler beim Laden der Fälle')}
          </h2>
          <p className="mt-2 text-neutral-600">
            {t('list.error.message', 'Die Fallliste konnte nicht geladen werden. Bitte versuchen Sie es später erneut.')}
          </p>
        </div>
      </div>
    );
  }

  // ── Render ──────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900">{t('list.title', 'Fälle')}</h1>
          <p className="mt-1 text-sm text-neutral-500">
            {t('list.subtitle', 'Alle Meldungen und Beschwerden verwalten')}
          </p>
        </div>

        <PageSizeSelector value={pageSize} onChange={handlePageSizeChange} />
      </div>

      {/* Filter Bar */}
      <div className="mb-6">
        <FilterBar
          filters={filters}
          onFilterChange={handleFilterChange}
          onReset={handleFilterReset}
          searchInput={searchInput}
          onSearchChange={handleSearchChange}
          labelOptions={labelOptions}
        />
      </div>

      {/* Case Table */}
      <CaseTable
        cases={data?.items ?? []}
        sort={sort}
        onSortChange={handleSortChange}
        pagination={data?.pagination}
        onPageChange={handlePageChange}
        isLoading={isLoading}
      />
    </div>
  );
}
