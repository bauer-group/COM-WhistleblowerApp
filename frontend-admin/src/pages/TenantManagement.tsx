/**
 * Hinweisgebersystem – Tenant Management Page.
 *
 * Full-featured tenant CRUD with:
 * - Paginated tenant list with active/inactive filter
 * - Search on tenant name and slug
 * - Create tenant dialog
 * - Edit tenant dialog with branding and configuration editing
 * - Inline activation/deactivation
 *
 * Requires system_admin role. Data is fetched via TanStack Query hooks.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTenants, useCreateTenant, useUpdateTenant } from '@/hooks/useCases';
import type {
  TenantResponse,
  TenantCreateRequest,
  TenantUpdateRequest,
  TenantListParams,
  TenantConfig,
  TenantBranding,
  TenantSMTPConfig,
} from '@/api/tenants';

// ── Types ─────────────────────────────────────────────────────

interface TenantFormData {
  name: string;
  slug: string;
  is_active: boolean;
  branding: TenantBranding;
  smtp: TenantSMTPConfig | null;
  languages: string[];
  default_language: string;
  retention_hinschg_years: number;
  retention_lksg_years: number;
}

const DEFAULT_BRANDING: TenantBranding = {
  logo_url: null,
  primary_color: null,
  accent_color: null,
};

const INITIAL_FORM_DATA: TenantFormData = {
  name: '',
  slug: '',
  is_active: true,
  branding: { ...DEFAULT_BRANDING },
  smtp: null,
  languages: ['de'],
  default_language: 'de',
  retention_hinschg_years: 3,
  retention_lksg_years: 5,
};

// ── Debounced Search Hook ─────────────────────────────────────

function useDebouncedSearch(delay = 400) {
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [timerId, setTimerId] = useState<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchInput(value);
      if (timerId) clearTimeout(timerId);
      const id = setTimeout(() => setDebouncedSearch(value), delay);
      setTimerId(id);
    },
    [delay, timerId],
  );

  return { searchInput, debouncedSearch, handleSearchChange };
}

// ── Tenant Form Dialog ────────────────────────────────────────

interface TenantFormDialogProps {
  isOpen: boolean;
  isEditing: boolean;
  formData: TenantFormData;
  version: number;
  onFormChange: (key: keyof TenantFormData, value: unknown) => void;
  onBrandingChange: (key: keyof TenantBranding, value: string | null) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isSubmitting: boolean;
  error: string | null;
}

function TenantFormDialog({
  isOpen,
  isEditing,
  formData,
  onFormChange,
  onBrandingChange,
  onSubmit,
  onCancel,
  isSubmitting,
  error,
}: TenantFormDialogProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label={isEditing ? 'Mandant bearbeiten' : 'Mandant erstellen'}
    >
      <div className="mx-4 max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-neutral-900">
          {isEditing ? 'Mandant bearbeiten' : 'Mandant erstellen'}
        </h2>

        {error && (
          <div
            className="mb-4 rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="space-y-6">
          {/* Basic Info */}
          <fieldset>
            <legend className="mb-3 text-sm font-semibold text-neutral-800">Grunddaten</legend>
            <div className="space-y-4">
              <div>
                <label htmlFor="tenant-name" className="mb-1 block text-sm font-medium text-neutral-700">
                  Organisationsname
                </label>
                <input
                  id="tenant-name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => onFormChange('name', e.target.value)}
                  placeholder="Musterorganisation GmbH"
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div>
                <label htmlFor="tenant-slug" className="mb-1 block text-sm font-medium text-neutral-700">
                  URL-Slug
                </label>
                <input
                  id="tenant-slug"
                  type="text"
                  value={formData.slug}
                  onChange={(e) => onFormChange('slug', e.target.value)}
                  placeholder="muster-org"
                  disabled={isEditing}
                  className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-neutral-100 disabled:text-neutral-500"
                />
              </div>
              {isEditing && (
                <div className="flex items-center gap-2">
                  <input
                    id="tenant-active"
                    type="checkbox"
                    checked={formData.is_active}
                    onChange={(e) => onFormChange('is_active', e.target.checked)}
                    className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
                  />
                  <label htmlFor="tenant-active" className="text-sm font-medium text-neutral-700">
                    Mandant aktiv
                  </label>
                </div>
              )}
            </div>
          </fieldset>

          {/* Branding */}
          {isEditing && (
            <fieldset>
              <legend className="mb-3 text-sm font-semibold text-neutral-800">Branding</legend>
              <div className="space-y-4">
                <div>
                  <label htmlFor="tenant-logo" className="mb-1 block text-sm font-medium text-neutral-700">
                    Logo-URL
                  </label>
                  <input
                    id="tenant-logo"
                    type="url"
                    value={formData.branding.logo_url ?? ''}
                    onChange={(e) => onBrandingChange('logo_url', e.target.value || null)}
                    placeholder="https://..."
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="tenant-primary-color" className="mb-1 block text-sm font-medium text-neutral-700">
                      Primärfarbe
                    </label>
                    <div className="flex gap-2">
                      <input
                        id="tenant-primary-color"
                        type="color"
                        value={formData.branding.primary_color ?? '#1e40af'}
                        onChange={(e) => onBrandingChange('primary_color', e.target.value)}
                        className="h-10 w-12 cursor-pointer rounded border border-neutral-300"
                      />
                      <input
                        type="text"
                        value={formData.branding.primary_color ?? ''}
                        onChange={(e) => onBrandingChange('primary_color', e.target.value || null)}
                        placeholder="#1e40af"
                        className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="tenant-accent-color" className="mb-1 block text-sm font-medium text-neutral-700">
                      Akzentfarbe
                    </label>
                    <div className="flex gap-2">
                      <input
                        id="tenant-accent-color"
                        type="color"
                        value={formData.branding.accent_color ?? '#3b82f6'}
                        onChange={(e) => onBrandingChange('accent_color', e.target.value)}
                        className="h-10 w-12 cursor-pointer rounded border border-neutral-300"
                      />
                      <input
                        type="text"
                        value={formData.branding.accent_color ?? ''}
                        onChange={(e) => onBrandingChange('accent_color', e.target.value || null)}
                        placeholder="#3b82f6"
                        className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </div>
                </div>
              </div>
            </fieldset>
          )}

          {/* Language & Retention (shown for edit) */}
          {isEditing && (
            <fieldset>
              <legend className="mb-3 text-sm font-semibold text-neutral-800">
                Sprachen & Aufbewahrung
              </legend>
              <div className="space-y-4">
                <div>
                  <label htmlFor="tenant-default-lang" className="mb-1 block text-sm font-medium text-neutral-700">
                    Standardsprache
                  </label>
                  <select
                    id="tenant-default-lang"
                    value={formData.default_language}
                    onChange={(e) => onFormChange('default_language', e.target.value)}
                    className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="de">Deutsch</option>
                    <option value="en">Englisch</option>
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="tenant-retention-hinschg"
                      className="mb-1 block text-sm font-medium text-neutral-700"
                    >
                      HinSchG-Aufbewahrung (Jahre)
                    </label>
                    <input
                      id="tenant-retention-hinschg"
                      type="number"
                      min={1}
                      max={10}
                      value={formData.retention_hinschg_years}
                      onChange={(e) => onFormChange('retention_hinschg_years', Number(e.target.value))}
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="tenant-retention-lksg"
                      className="mb-1 block text-sm font-medium text-neutral-700"
                    >
                      LkSG-Aufbewahrung (Jahre)
                    </label>
                    <input
                      id="tenant-retention-lksg"
                      type="number"
                      min={1}
                      max={10}
                      value={formData.retention_lksg_years}
                      onChange={(e) => onFormChange('retention_lksg_years', Number(e.target.value))}
                      className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>
              </div>
            </fieldset>
          )}
        </div>

        {/* Actions */}
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50 disabled:opacity-50"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitting}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {isSubmitting ? 'Wird gespeichert...' : isEditing ? 'Speichern' : 'Erstellen'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── TenantManagement Page ─────────────────────────────────────

export default function TenantManagement() {
  // ── State ───────────────────────────────────────────────────
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [activeFilter, setActiveFilter] = useState<'' | 'true' | 'false'>('');
  const { searchInput, debouncedSearch, handleSearchChange } = useDebouncedSearch();

  // ── Dialog State ────────────────────────────────────────────
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editingTenantId, setEditingTenantId] = useState<string | null>(null);
  const [editingVersion, setEditingVersion] = useState(0);
  const [formData, setFormData] = useState<TenantFormData>(INITIAL_FORM_DATA);
  const [formError, setFormError] = useState<string | null>(null);

  // ── Query Parameters ────────────────────────────────────────
  const queryParams = useMemo<TenantListParams>(() => {
    const params: TenantListParams = { page, page_size: pageSize };
    if (activeFilter) params.is_active = activeFilter === 'true';
    if (debouncedSearch) params.search = debouncedSearch;
    return params;
  }, [page, pageSize, activeFilter, debouncedSearch]);

  const { data, isLoading, error } = useTenants({ params: queryParams });
  const createTenantMutation = useCreateTenant();
  const updateTenantMutation = useUpdateTenant();

  // ── Handlers ────────────────────────────────────────────────

  const handleFormChange = useCallback(
    (key: keyof TenantFormData, value: unknown) => {
      setFormData((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleBrandingChange = useCallback(
    (key: keyof TenantBranding, value: string | null) => {
      setFormData((prev) => ({
        ...prev,
        branding: { ...prev.branding, [key]: value },
      }));
    },
    [],
  );

  const openCreateDialog = useCallback(() => {
    setFormData(INITIAL_FORM_DATA);
    setFormError(null);
    setIsEditing(false);
    setEditingTenantId(null);
    setEditingVersion(0);
    setIsDialogOpen(true);
  }, []);

  const openEditDialog = useCallback((tenant: TenantResponse) => {
    setFormData({
      name: tenant.name,
      slug: tenant.slug,
      is_active: tenant.is_active,
      branding: { ...tenant.config.branding },
      smtp: tenant.config.smtp ? { ...tenant.config.smtp } : null,
      languages: [...tenant.config.languages],
      default_language: tenant.config.default_language,
      retention_hinschg_years: tenant.config.retention_hinschg_years,
      retention_lksg_years: tenant.config.retention_lksg_years,
    });
    setFormError(null);
    setIsEditing(true);
    setEditingTenantId(tenant.id);
    setEditingVersion(tenant.version);
    setIsDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => {
    setIsDialogOpen(false);
    setFormError(null);
  }, []);

  const handleSubmit = useCallback(() => {
    setFormError(null);

    if (isEditing && editingTenantId) {
      const config: TenantConfig = {
        branding: formData.branding,
        smtp: formData.smtp,
        languages: formData.languages,
        default_language: formData.default_language,
        retention_hinschg_years: formData.retention_hinschg_years,
        retention_lksg_years: formData.retention_lksg_years,
      };

      const updateData: TenantUpdateRequest = {
        name: formData.name,
        is_active: formData.is_active,
        config,
        version: editingVersion,
      };

      updateTenantMutation.mutate(
        { tenantId: editingTenantId, data: updateData },
        {
          onSuccess: () => closeDialog(),
          onError: (err) => setFormError(err.message),
        },
      );
    } else {
      const createData: TenantCreateRequest = {
        slug: formData.slug,
        name: formData.name,
      };

      createTenantMutation.mutate(createData, {
        onSuccess: () => closeDialog(),
        onError: (err) => setFormError(err.message),
      });
    }
  }, [
    isEditing,
    editingTenantId,
    editingVersion,
    formData,
    updateTenantMutation,
    createTenantMutation,
    closeDialog,
  ]);

  const handleToggleActive = useCallback(
    (tenant: TenantResponse) => {
      updateTenantMutation.mutate({
        tenantId: tenant.id,
        data: { is_active: !tenant.is_active, version: tenant.version },
      });
    },
    [updateTenantMutation],
  );

  const formatDate = useCallback((dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  }, []);

  // ── Error State ─────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">Fehler beim Laden der Mandanten</h2>
          <p className="mt-2 text-neutral-600">
            Die Mandantenliste konnte nicht geladen werden. Bitte versuchen Sie es später erneut.
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
          <h1 className="text-2xl font-bold text-neutral-900">Mandantenverwaltung</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Organisationen und deren Konfiguration verwalten
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateDialog}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
        >
          Mandant erstellen
        </button>
      </div>

      {/* Filter Bar */}
      <div className="mb-6 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
        <div className="mb-4">
          <label htmlFor="tenant-search" className="sr-only">
            Mandant suchen
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
              id="tenant-search"
              type="search"
              placeholder="Mandant suchen (Name, Slug)..."
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full rounded-md border border-neutral-300 py-2 pl-10 pr-4 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[140px]">
            <label htmlFor="filter-tenant-active" className="mb-1 block text-xs font-medium text-neutral-600">
              Status
            </label>
            <select
              id="filter-tenant-active"
              value={activeFilter}
              onChange={(e) => {
                setActiveFilter(e.target.value as '' | 'true' | 'false');
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle</option>
              <option value="true">Aktiv</option>
              <option value="false">Inaktiv</option>
            </select>
          </div>
        </div>
      </div>

      {/* Tenant Table */}
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-neutral-200">
            <thead className="bg-neutral-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Slug
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Sprachen
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Erstellt am
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Aktionen
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 6 }).map((__, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 w-24 animate-pulse rounded bg-neutral-200" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !data?.items?.length ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-neutral-500">
                    Keine Mandanten gefunden.
                  </td>
                </tr>
              ) : (
                data.items.map((tenant) => (
                  <tr key={tenant.id} className="transition-colors hover:bg-neutral-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-neutral-900">
                      {tenant.name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs">
                        {tenant.slug}
                      </code>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          tenant.is_active
                            ? 'bg-success/10 text-success'
                            : 'bg-neutral-100 text-neutral-500'
                        }`}
                      >
                        {tenant.is_active ? 'Aktiv' : 'Inaktiv'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {tenant.config.languages.join(', ').toUpperCase()}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-500">
                      {formatDate(tenant.created_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => openEditDialog(tenant)}
                          className="rounded-md px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                        >
                          Bearbeiten
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleActive(tenant)}
                          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                            tenant.is_active
                              ? 'text-danger hover:bg-danger/10'
                              : 'text-success hover:bg-success/10'
                          }`}
                        >
                          {tenant.is_active ? 'Deaktivieren' : 'Aktivieren'}
                        </button>
                      </div>
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

      {/* Create/Edit Dialog */}
      <TenantFormDialog
        isOpen={isDialogOpen}
        isEditing={isEditing}
        formData={formData}
        version={editingVersion}
        onFormChange={handleFormChange}
        onBrandingChange={handleBrandingChange}
        onSubmit={handleSubmit}
        onCancel={closeDialog}
        isSubmitting={createTenantMutation.isPending || updateTenantMutation.isPending}
        error={formError}
      />
    </div>
  );
}
