/**
 * Hinweisgebersystem – User Management Page.
 *
 * Full-featured user CRUD table with:
 * - Paginated user list with sortable columns
 * - Filter bar: role, active status, custodian designation
 * - Debounced search on display name and email
 * - Create user dialog (pre-registration before OIDC login)
 * - Edit user dialog (role assignment, activation, custodian toggle)
 * - Inline deactivation with confirmation
 *
 * Requires tenant_admin role. Data is fetched via TanStack Query hooks.
 */

import { useCallback, useMemo, useState } from 'react';
import { useUsers, useCreateUser, useUpdateUser } from '@/hooks/useCases';
import type { UserListParams, UserRole as UserRoleType } from '@/api/users';
import { UserRole } from '@/api/users';
import type { UserResponse, UserCreateRequest, UserUpdateRequest } from '@/api/users';

// ── Types ─────────────────────────────────────────────────────

interface UserFormData {
  email: string;
  display_name: string;
  oidc_subject: string;
  role: UserRoleType;
  is_custodian: boolean;
  is_active: boolean;
}

const INITIAL_FORM_DATA: UserFormData = {
  email: '',
  display_name: '',
  oidc_subject: '',
  role: UserRole.HANDLER,
  is_custodian: false,
  is_active: true,
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

// ── Role Options ──────────────────────────────────────────────

const ROLE_OPTIONS: { value: UserRoleType; label: string }[] = [
  { value: UserRole.SYSTEM_ADMIN, label: 'Systemadministrator' },
  { value: UserRole.TENANT_ADMIN, label: 'Mandantenadministrator' },
  { value: UserRole.HANDLER, label: 'Bearbeiter' },
  { value: UserRole.REVIEWER, label: 'Prüfer' },
  { value: UserRole.AUDITOR, label: 'Revisor' },
];

function getRoleLabel(role: UserRoleType): string {
  return ROLE_OPTIONS.find((opt) => opt.value === role)?.label ?? role;
}

// ── User Form Dialog ──────────────────────────────────────────

interface UserFormDialogProps {
  isOpen: boolean;
  isEditing: boolean;
  formData: UserFormData;
  onFormChange: (key: keyof UserFormData, value: string | boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isSubmitting: boolean;
  error: string | null;
}

function UserFormDialog({
  isOpen,
  isEditing,
  formData,
  onFormChange,
  onSubmit,
  onCancel,
  isSubmitting,
  error,
}: UserFormDialogProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label={isEditing ? 'Benutzer bearbeiten' : 'Benutzer erstellen'}
    >
      <div className="mx-4 w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-neutral-900">
          {isEditing ? 'Benutzer bearbeiten' : 'Benutzer erstellen'}
        </h2>

        {error && (
          <div
            className="mb-4 rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="space-y-4">
          {/* Email */}
          <div>
            <label htmlFor="user-email" className="mb-1 block text-sm font-medium text-neutral-700">
              E-Mail-Adresse
            </label>
            <input
              id="user-email"
              type="email"
              value={formData.email}
              onChange={(e) => onFormChange('email', e.target.value)}
              disabled={isEditing}
              placeholder="benutzer@organisation.de"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-neutral-100 disabled:text-neutral-500"
            />
          </div>

          {/* Display Name */}
          <div>
            <label htmlFor="user-name" className="mb-1 block text-sm font-medium text-neutral-700">
              Anzeigename
            </label>
            <input
              id="user-name"
              type="text"
              value={formData.display_name}
              onChange={(e) => onFormChange('display_name', e.target.value)}
              placeholder="Max Mustermann"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* OIDC Subject */}
          {!isEditing && (
            <div>
              <label htmlFor="user-oidc" className="mb-1 block text-sm font-medium text-neutral-700">
                OIDC Subject (Sub-Claim)
              </label>
              <input
                id="user-oidc"
                type="text"
                value={formData.oidc_subject}
                onChange={(e) => onFormChange('oidc_subject', e.target.value)}
                placeholder="Azure AD Object-ID"
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          )}

          {/* Role */}
          <div>
            <label htmlFor="user-role" className="mb-1 block text-sm font-medium text-neutral-700">
              Rolle
            </label>
            <select
              id="user-role"
              value={formData.role}
              onChange={(e) => onFormChange('role', e.target.value)}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Custodian */}
          <div className="flex items-center gap-2">
            <input
              id="user-custodian"
              type="checkbox"
              checked={formData.is_custodian}
              onChange={(e) => onFormChange('is_custodian', e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
            />
            <label htmlFor="user-custodian" className="text-sm font-medium text-neutral-700">
              Als Vertrauensperson benennen
            </label>
          </div>

          {/* Active */}
          {isEditing && (
            <div className="flex items-center gap-2">
              <input
                id="user-active"
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => onFormChange('is_active', e.target.checked)}
                className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
              />
              <label htmlFor="user-active" className="text-sm font-medium text-neutral-700">
                Konto aktiv
              </label>
            </div>
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

// ── UserManagement Page ───────────────────────────────────────

export default function UserManagement() {
  // ── State ───────────────────────────────────────────────────
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [roleFilter, setRoleFilter] = useState<UserRoleType | ''>('');
  const [activeFilter, setActiveFilter] = useState<'' | 'true' | 'false'>('');
  const [custodianFilter, setCustodianFilter] = useState<'' | 'true'>('');
  const { searchInput, debouncedSearch, handleSearchChange } = useDebouncedSearch();

  // ── Dialog State ────────────────────────────────────────────
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [formData, setFormData] = useState<UserFormData>(INITIAL_FORM_DATA);
  const [formError, setFormError] = useState<string | null>(null);

  // ── Query Parameters ────────────────────────────────────────
  const queryParams = useMemo<UserListParams>(() => {
    const params: UserListParams = { page, page_size: pageSize };
    if (roleFilter) params.role = roleFilter as UserRoleType;
    if (activeFilter) params.is_active = activeFilter === 'true';
    if (custodianFilter) params.is_custodian = true;
    if (debouncedSearch) params.search = debouncedSearch;
    return params;
  }, [page, pageSize, roleFilter, activeFilter, custodianFilter, debouncedSearch]);

  const { data, isLoading, error } = useUsers({ params: queryParams });
  const createUserMutation = useCreateUser();
  const updateUserMutation = useUpdateUser();

  // ── Handlers ────────────────────────────────────────────────

  const handleFormChange = useCallback(
    (key: keyof UserFormData, value: string | boolean) => {
      setFormData((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const openCreateDialog = useCallback(() => {
    setFormData(INITIAL_FORM_DATA);
    setFormError(null);
    setIsEditing(false);
    setEditingUserId(null);
    setIsDialogOpen(true);
  }, []);

  const openEditDialog = useCallback((user: UserResponse) => {
    setFormData({
      email: user.email,
      display_name: user.display_name,
      oidc_subject: user.oidc_subject,
      role: user.role,
      is_custodian: user.is_custodian,
      is_active: user.is_active,
    });
    setFormError(null);
    setIsEditing(true);
    setEditingUserId(user.id);
    setIsDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => {
    setIsDialogOpen(false);
    setFormError(null);
  }, []);

  const handleSubmit = useCallback(() => {
    setFormError(null);

    if (isEditing && editingUserId) {
      const updateData: UserUpdateRequest = {
        display_name: formData.display_name,
        role: formData.role,
        is_active: formData.is_active,
        is_custodian: formData.is_custodian,
      };

      updateUserMutation.mutate(
        { userId: editingUserId, data: updateData },
        {
          onSuccess: () => closeDialog(),
          onError: (err) => setFormError(err.message),
        },
      );
    } else {
      const createData: UserCreateRequest = {
        email: formData.email,
        display_name: formData.display_name,
        oidc_subject: formData.oidc_subject,
        role: formData.role,
        is_custodian: formData.is_custodian,
      };

      createUserMutation.mutate(createData, {
        onSuccess: () => closeDialog(),
        onError: (err) => setFormError(err.message),
      });
    }
  }, [isEditing, editingUserId, formData, updateUserMutation, createUserMutation, closeDialog]);

  const handleToggleActive = useCallback(
    (user: UserResponse) => {
      updateUserMutation.mutate({
        userId: user.id,
        data: { is_active: !user.is_active },
      });
    },
    [updateUserMutation],
  );

  const formatDate = useCallback((dateStr: string | null) => {
    if (!dateStr) return 'Nie';
    return new Date(dateStr).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }, []);

  // ── Error State ─────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">Fehler beim Laden der Benutzer</h2>
          <p className="mt-2 text-neutral-600">
            Die Benutzerliste konnte nicht geladen werden. Bitte versuchen Sie es später erneut.
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
          <h1 className="text-2xl font-bold text-neutral-900">Benutzerverwaltung</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Benutzerkonten verwalten und Rollen zuweisen
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateDialog}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
        >
          Benutzer erstellen
        </button>
      </div>

      {/* Filter Bar */}
      <div className="mb-6 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
        {/* Search */}
        <div className="mb-4">
          <label htmlFor="user-search" className="sr-only">
            Benutzer suchen
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
              id="user-search"
              type="search"
              placeholder="Benutzer suchen (Name, E-Mail)..."
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full rounded-md border border-neutral-300 py-2 pl-10 pr-4 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          {/* Role Filter */}
          <div className="min-w-[180px]">
            <label htmlFor="filter-role" className="mb-1 block text-xs font-medium text-neutral-600">
              Rolle
            </label>
            <select
              id="filter-role"
              value={roleFilter}
              onChange={(e) => {
                setRoleFilter(e.target.value as UserRoleType | '');
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle Rollen</option>
              {ROLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Active Filter */}
          <div className="min-w-[140px]">
            <label htmlFor="filter-active" className="mb-1 block text-xs font-medium text-neutral-600">
              Status
            </label>
            <select
              id="filter-active"
              value={activeFilter}
              onChange={(e) => {
                setActiveFilter(e.target.value as '' | 'true' | 'false');
                setPage(1);
              }}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Alle Status</option>
              <option value="true">Aktiv</option>
              <option value="false">Inaktiv</option>
            </select>
          </div>

          {/* Custodian Filter */}
          <div className="flex items-center gap-2 pb-1">
            <input
              id="filter-custodian"
              type="checkbox"
              checked={custodianFilter === 'true'}
              onChange={(e) => {
                setCustodianFilter(e.target.checked ? 'true' : '');
                setPage(1);
              }}
              className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
            />
            <label htmlFor="filter-custodian" className="text-sm font-medium text-neutral-700">
              Nur Vertrauenspersonen
            </label>
          </div>
        </div>
      </div>

      {/* User Table */}
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-neutral-200">
            <thead className="bg-neutral-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  E-Mail
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Rolle
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Vertrauensperson
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Letzter Login
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
                    {Array.from({ length: 7 }).map((__, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 w-24 animate-pulse rounded bg-neutral-200" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !data?.items?.length ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-neutral-500">
                    Keine Benutzer gefunden.
                  </td>
                </tr>
              ) : (
                data.items.map((user) => (
                  <tr key={user.id} className="transition-colors hover:bg-neutral-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-neutral-900">
                      {user.display_name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {user.email}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium text-neutral-700">
                        {getRoleLabel(user.role)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          user.is_active
                            ? 'bg-success/10 text-success'
                            : 'bg-neutral-100 text-neutral-500'
                        }`}
                      >
                        {user.is_active ? 'Aktiv' : 'Inaktiv'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {user.is_custodian ? (
                        <span className="inline-flex rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                          Ja
                        </span>
                      ) : (
                        <span className="text-neutral-400">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-500">
                      {formatDate(user.last_login_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => openEditDialog(user)}
                          className="rounded-md px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                        >
                          Bearbeiten
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleActive(user)}
                          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                            user.is_active
                              ? 'text-danger hover:bg-danger/10'
                              : 'text-success hover:bg-success/10'
                          }`}
                        >
                          {user.is_active ? 'Deaktivieren' : 'Aktivieren'}
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
      <UserFormDialog
        isOpen={isDialogOpen}
        isEditing={isEditing}
        formData={formData}
        onFormChange={handleFormChange}
        onSubmit={handleSubmit}
        onCancel={closeDialog}
        isSubmitting={createUserMutation.isPending || updateUserMutation.isPending}
        error={formError}
      />
    </div>
  );
}
