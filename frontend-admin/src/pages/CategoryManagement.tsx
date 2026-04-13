/**
 * Hinweisgebersystem – Category Management Page.
 *
 * Full-featured category CRUD per language with:
 * - Language selector to switch between DE/EN translations
 * - Category table with sort order, label, description, active status
 * - Create category dialog for new category keys
 * - Edit category dialog for updating translations and metadata
 * - Inline activation/deactivation
 *
 * Categories use a shared ``category_key`` across languages, with
 * per-language ``label`` and ``description`` translations.
 *
 * Requires tenant_admin role. Data is fetched via TanStack Query hooks.
 */

import { useCallback, useState } from 'react';
import { useCategories, useCreateCategory, useUpdateCategory } from '@/hooks/useCases';
import { useAuth } from '@/hooks/useAuth';
import type {
  CategoryResponse,
  CategoryCreateRequest,
  CategoryUpdateRequest,
} from '@/api/tenants';

// ── Types ─────────────────────────────────────────────────────

interface CategoryFormData {
  category_key: string;
  label: string;
  description: string;
  sort_order: number;
  is_active: boolean;
}

const INITIAL_FORM_DATA: CategoryFormData = {
  category_key: '',
  label: '',
  description: '',
  sort_order: 0,
  is_active: true,
};

const LANGUAGE_OPTIONS = [
  { value: 'de', label: 'Deutsch' },
  { value: 'en', label: 'Englisch' },
];

// ── Category Form Dialog ──────────────────────────────────────

interface CategoryFormDialogProps {
  isOpen: boolean;
  isEditing: boolean;
  formData: CategoryFormData;
  onFormChange: (key: keyof CategoryFormData, value: string | number | boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isSubmitting: boolean;
  error: string | null;
  selectedLanguage: string;
}

function CategoryFormDialog({
  isOpen,
  isEditing,
  formData,
  onFormChange,
  onSubmit,
  onCancel,
  isSubmitting,
  error,
  selectedLanguage,
}: CategoryFormDialogProps) {
  if (!isOpen) return null;

  const languageLabel = LANGUAGE_OPTIONS.find((l) => l.value === selectedLanguage)?.label ?? selectedLanguage;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label={isEditing ? 'Kategorie bearbeiten' : 'Kategorie erstellen'}
    >
      <div className="mx-4 w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-1 text-lg font-semibold text-neutral-900">
          {isEditing ? 'Kategorie bearbeiten' : 'Kategorie erstellen'}
        </h2>
        <p className="mb-4 text-sm text-neutral-500">
          Sprache: {languageLabel}
        </p>

        {error && (
          <div
            className="mb-4 rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="space-y-4">
          {/* Category Key */}
          <div>
            <label htmlFor="cat-key" className="mb-1 block text-sm font-medium text-neutral-700">
              Kategorieschlüssel
            </label>
            <input
              id="cat-key"
              type="text"
              value={formData.category_key}
              onChange={(e) => onFormChange('category_key', e.target.value)}
              disabled={isEditing}
              placeholder="z.B. korruption, betrug"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-neutral-100 disabled:text-neutral-500"
            />
          </div>

          {/* Label */}
          <div>
            <label htmlFor="cat-label" className="mb-1 block text-sm font-medium text-neutral-700">
              Bezeichnung
            </label>
            <input
              id="cat-label"
              type="text"
              value={formData.label}
              onChange={(e) => onFormChange('label', e.target.value)}
              placeholder="Anzeigename der Kategorie"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Description */}
          <div>
            <label htmlFor="cat-desc" className="mb-1 block text-sm font-medium text-neutral-700">
              Beschreibung
            </label>
            <textarea
              id="cat-desc"
              value={formData.description}
              onChange={(e) => onFormChange('description', e.target.value)}
              placeholder="Optionale Beschreibung für den Hinweisgeber"
              rows={3}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Sort Order */}
          <div>
            <label htmlFor="cat-sort" className="mb-1 block text-sm font-medium text-neutral-700">
              Sortierreihenfolge
            </label>
            <input
              id="cat-sort"
              type="number"
              min={0}
              value={formData.sort_order}
              onChange={(e) => onFormChange('sort_order', Number(e.target.value))}
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Active */}
          {isEditing && (
            <div className="flex items-center gap-2">
              <input
                id="cat-active"
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => onFormChange('is_active', e.target.checked)}
                className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
              />
              <label htmlFor="cat-active" className="text-sm font-medium text-neutral-700">
                Kategorie aktiv
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

// ── CategoryManagement Page ───────────────────────────────────

export default function CategoryManagement() {
  const { user } = useAuth();
  const tenantId = user?.tenantId ?? '';

  // ── State ───────────────────────────────────────────────────
  const [selectedLanguage, setSelectedLanguage] = useState('de');

  // ── Dialog State ────────────────────────────────────────────
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState<string | null>(null);
  const [formData, setFormData] = useState<CategoryFormData>(INITIAL_FORM_DATA);
  const [formError, setFormError] = useState<string | null>(null);

  // ── Queries ─────────────────────────────────────────────────
  const { data: categories, isLoading, error } = useCategories({
    tenantId,
    language: selectedLanguage,
    enabled: !!tenantId,
  });
  const createCategoryMutation = useCreateCategory();
  const updateCategoryMutation = useUpdateCategory();

  // ── Handlers ────────────────────────────────────────────────

  const handleFormChange = useCallback(
    (key: keyof CategoryFormData, value: string | number | boolean) => {
      setFormData((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const openCreateDialog = useCallback(() => {
    setFormData(INITIAL_FORM_DATA);
    setFormError(null);
    setIsEditing(false);
    setEditingCategoryId(null);
    setIsDialogOpen(true);
  }, []);

  const openEditDialog = useCallback((category: CategoryResponse) => {
    setFormData({
      category_key: category.category_key,
      label: category.label,
      description: category.description ?? '',
      sort_order: category.sort_order,
      is_active: category.is_active,
    });
    setFormError(null);
    setIsEditing(true);
    setEditingCategoryId(category.id);
    setIsDialogOpen(true);
  }, []);

  const closeDialog = useCallback(() => {
    setIsDialogOpen(false);
    setFormError(null);
  }, []);

  const handleSubmit = useCallback(() => {
    setFormError(null);

    if (isEditing && editingCategoryId) {
      const updateData: CategoryUpdateRequest = {
        label: formData.label,
        description: formData.description || undefined,
        sort_order: formData.sort_order,
        is_active: formData.is_active,
      };

      updateCategoryMutation.mutate(
        {
          tenantId,
          language: selectedLanguage,
          categoryId: editingCategoryId,
          data: updateData,
        },
        {
          onSuccess: () => closeDialog(),
          onError: (err) => setFormError(err.message),
        },
      );
    } else {
      const createData: CategoryCreateRequest = {
        category_key: formData.category_key,
        label: formData.label,
        description: formData.description || undefined,
        sort_order: formData.sort_order,
      };

      createCategoryMutation.mutate(
        {
          tenantId,
          language: selectedLanguage,
          data: createData,
        },
        {
          onSuccess: () => closeDialog(),
          onError: (err) => setFormError(err.message),
        },
      );
    }
  }, [
    isEditing,
    editingCategoryId,
    tenantId,
    selectedLanguage,
    formData,
    updateCategoryMutation,
    createCategoryMutation,
    closeDialog,
  ]);

  const handleToggleActive = useCallback(
    (category: CategoryResponse) => {
      updateCategoryMutation.mutate({
        tenantId,
        language: selectedLanguage,
        categoryId: category.id,
        data: { is_active: !category.is_active },
      });
    },
    [tenantId, selectedLanguage, updateCategoryMutation],
  );

  // ── Error State ─────────────────────────────────────────────

  if (error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-6 text-center" role="alert">
          <h2 className="text-lg font-semibold text-danger">Fehler beim Laden der Kategorien</h2>
          <p className="mt-2 text-neutral-600">
            Die Kategorien konnten nicht geladen werden. Bitte versuchen Sie es später erneut.
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
          <h1 className="text-2xl font-bold text-neutral-900">Kategorieverwaltung</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Meldekategorien und Übersetzungen verwalten
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateDialog}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90"
        >
          Kategorie erstellen
        </button>
      </div>

      {/* Language Selector */}
      <div className="mb-6 rounded-lg border border-neutral-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <label htmlFor="cat-language" className="text-sm font-medium text-neutral-700">
            Sprache auswählen:
          </label>
          <select
            id="cat-language"
            value={selectedLanguage}
            onChange={(e) => setSelectedLanguage(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Category Table */}
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-neutral-200">
            <thead className="bg-neutral-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Reihenfolge
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Schlüssel
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Bezeichnung
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Beschreibung
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-600">
                  Status
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
              ) : !categories?.length ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-neutral-500">
                    Keine Kategorien für diese Sprache gefunden.
                  </td>
                </tr>
              ) : (
                categories.map((category) => (
                  <tr key={category.id} className="transition-colors hover:bg-neutral-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      {category.sort_order}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-neutral-600">
                      <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs">
                        {category.category_key}
                      </code>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-neutral-900">
                      {category.label}
                    </td>
                    <td className="max-w-xs truncate px-4 py-3 text-sm text-neutral-600">
                      {category.description ?? (
                        <span className="text-neutral-400">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          category.is_active
                            ? 'bg-success/10 text-success'
                            : 'bg-neutral-100 text-neutral-500'
                        }`}
                      >
                        {category.is_active ? 'Aktiv' : 'Inaktiv'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => openEditDialog(category)}
                          className="rounded-md px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                        >
                          Bearbeiten
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleActive(category)}
                          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                            category.is_active
                              ? 'text-danger hover:bg-danger/10'
                              : 'text-success hover:bg-success/10'
                          }`}
                        >
                          {category.is_active ? 'Deaktivieren' : 'Aktivieren'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create/Edit Dialog */}
      <CategoryFormDialog
        isOpen={isDialogOpen}
        isEditing={isEditing}
        formData={formData}
        onFormChange={handleFormChange}
        onSubmit={handleSubmit}
        onCancel={closeDialog}
        isSubmitting={createCategoryMutation.isPending || updateCategoryMutation.isPending}
        error={formError}
        selectedLanguage={selectedLanguage}
      />
    </div>
  );
}
