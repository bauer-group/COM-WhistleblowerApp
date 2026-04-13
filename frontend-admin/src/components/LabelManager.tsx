/**
 * Hinweisgebersystem – LabelManager Component.
 *
 * Full CRUD management UI for tenant-scoped report labels.
 * Provides a list of existing labels with inline editing, a
 * creation form with colour picker, and soft-delete (deactivate)
 * functionality.
 *
 * Designed to be embedded in the Settings page as a tab panel.
 * Uses the labels API client for all server communication.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  LabelCreateRequest,
  LabelResponse,
  LabelUpdateRequest,
} from '@/api/labels';
import {
  getLabels,
  createLabel,
  updateLabel,
  deleteLabel,
} from '@/api/labels';
import LabelBadge from '@/components/LabelBadge';

// ── Types ─────────────────────────────────────────────────────

interface LabelManagerProps {
  /** Whether the user has permission to create/edit labels. */
  canEdit?: boolean;
}

// ── Preset Colours ────────────────────────────────────────────

const PRESET_COLORS = [
  '#EF4444', // Red
  '#F97316', // Orange
  '#EAB308', // Yellow
  '#22C55E', // Green
  '#14B8A6', // Teal
  '#3B82F6', // Blue
  '#6366F1', // Indigo
  '#8B5CF6', // Violet
  '#EC4899', // Pink
  '#6B7280', // Grey
  '#0EA5E9', // Sky
  '#84CC16', // Lime
] as const;

// ── Component ────────────────────────────────────────────────

/**
 * Label management UI with CRUD operations.
 *
 * Renders a list of existing labels with edit/deactivate controls
 * and a form for creating new labels with name, colour picker,
 * and optional description.
 */
export default function LabelManager({ canEdit = true }: LabelManagerProps) {
  const { t } = useTranslation('admin');

  // ── State ──────────────────────────────────────────────────
  const [labels, setLabels] = useState<LabelResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#3B82F6');
  const [newDescription, setNewDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [isUpdating, setIsUpdating] = useState(false);

  // ── Fetch Labels ───────────────────────────────────────────

  const fetchLabels = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await getLabels({ page_size: 100 });
      setLabels(response.items);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('labels.error.load', 'Fehler beim Laden der Labels.'),
      );
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchLabels();
  }, [fetchLabels]);

  // ── Create Handler ─────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;

    setIsCreating(true);
    setError(null);

    try {
      const data: LabelCreateRequest = {
        name: newName.trim(),
        color: newColor,
        description: newDescription.trim() || undefined,
      };

      const created = await createLabel(data);
      setLabels((prev) => [...prev, created]);
      setNewName('');
      setNewColor('#3B82F6');
      setNewDescription('');
      setShowCreateForm(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes('409')) {
        setError(t('labels.error.duplicate', 'Ein Label mit diesem Namen existiert bereits.'));
      } else {
        setError(
          err instanceof Error
            ? err.message
            : t('labels.error.create', 'Fehler beim Erstellen des Labels.'),
        );
      }
    } finally {
      setIsCreating(false);
    }
  }, [newName, newColor, newDescription, t]);

  // ── Edit Handlers ──────────────────────────────────────────

  const startEdit = useCallback((label: LabelResponse) => {
    setEditingId(label.id);
    setEditName(label.name);
    setEditColor(label.color);
    setEditDescription(label.description ?? '');
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditName('');
    setEditColor('');
    setEditDescription('');
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!editingId || !editName.trim()) return;

    setIsUpdating(true);
    setError(null);

    try {
      const data: LabelUpdateRequest = {
        name: editName.trim(),
        color: editColor,
        description: editDescription.trim() || undefined,
      };

      const updated = await updateLabel(editingId, data);
      setLabels((prev) =>
        prev.map((lbl) => (lbl.id === editingId ? updated : lbl)),
      );
      cancelEdit();
    } catch (err) {
      if (err instanceof Error && err.message.includes('409')) {
        setError(t('labels.error.duplicate', 'Ein Label mit diesem Namen existiert bereits.'));
      } else {
        setError(
          err instanceof Error
            ? err.message
            : t('labels.error.update', 'Fehler beim Aktualisieren des Labels.'),
        );
      }
    } finally {
      setIsUpdating(false);
    }
  }, [editingId, editName, editColor, editDescription, cancelEdit, t]);

  // ── Delete (Deactivate) Handler ────────────────────────────

  const handleDelete = useCallback(
    async (labelId: string) => {
      setError(null);

      try {
        await deleteLabel(labelId);
        setLabels((prev) =>
          prev.map((lbl) =>
            lbl.id === labelId ? { ...lbl, is_active: false } : lbl,
          ),
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('labels.error.delete', 'Fehler beim Deaktivieren des Labels.'),
        );
      }
    },
    [t],
  );

  // ── Reactivate Handler ─────────────────────────────────────

  const handleReactivate = useCallback(
    async (labelId: string) => {
      setError(null);

      try {
        const updated = await updateLabel(labelId, { is_active: true });
        setLabels((prev) =>
          prev.map((lbl) => (lbl.id === labelId ? updated : lbl)),
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('labels.error.update', 'Fehler beim Aktualisieren des Labels.'),
        );
      }
    },
    [t],
  );

  // ── Loading State ──────────────────────────────────────────

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-12"
        role="status"
        aria-label={t('labels.loading', 'Labels werden geladen...')}
      >
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  // ── Colour Picker Sub-Component ────────────────────────────

  const ColorPicker = ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (color: string) => void;
  }) => (
    <div className="flex flex-wrap gap-1.5">
      {PRESET_COLORS.map((preset) => (
        <button
          key={preset}
          type="button"
          onClick={() => onChange(preset)}
          className={`h-6 w-6 rounded-full border-2 transition-all ${
            value === preset
              ? 'border-neutral-900 ring-2 ring-primary/30'
              : 'border-transparent hover:border-neutral-400'
          }`}
          style={{ backgroundColor: preset }}
          aria-label={preset}
          aria-pressed={value === preset}
        />
      ))}
      <label className="flex items-center gap-1 text-xs text-neutral-500">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-6 w-6 cursor-pointer rounded border border-neutral-300"
          aria-label={t('labels.custom_color', 'Eigene Farbe')}
        />
      </label>
    </div>
  );

  // ── Render ─────────────────────────────────────────────────

  const activeLabels = labels.filter((lbl) => lbl.is_active);
  const inactiveLabels = labels.filter((lbl) => !lbl.is_active);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-neutral-900">
            {t('labels.title', 'Labels')}
          </h3>
          <p className="mt-1 text-sm text-neutral-500">
            {t(
              'labels.description',
              'Labels zur Kategorisierung und Filterung von Meldungen verwalten.',
            )}
          </p>
        </div>

        {canEdit && !showCreateForm && (
          <button
            type="button"
            onClick={() => setShowCreateForm(true)}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
          >
            {t('labels.create_button', 'Neues Label')}
          </button>
        )}
      </div>

      {/* Error Banner */}
      {error && (
        <div
          className="rounded-md border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Create Form */}
      {showCreateForm && canEdit && (
        <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4">
          <h4 className="mb-3 text-sm font-semibold text-neutral-700">
            {t('labels.create_title', 'Neues Label erstellen')}
          </h4>

          <div className="space-y-3">
            {/* Name Input */}
            <div>
              <label
                htmlFor="label-name"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                {t('labels.name', 'Name')} *
              </label>
              <input
                id="label-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t('labels.name_placeholder', 'z.B. Dringend, Compliance, Nachverfolgung...')}
                maxLength={100}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                autoFocus
              />
            </div>

            {/* Colour Picker */}
            <div>
              <label className="mb-1 block text-sm font-medium text-neutral-700">
                {t('labels.color', 'Farbe')}
              </label>
              <ColorPicker value={newColor} onChange={setNewColor} />
              {/* Preview */}
              {newName.trim() && (
                <div className="mt-2">
                  <span className="text-xs text-neutral-500">
                    {t('labels.preview', 'Vorschau:')}
                  </span>
                  <div className="mt-1">
                    <LabelBadge name={newName.trim()} color={newColor} />
                  </div>
                </div>
              )}
            </div>

            {/* Description Input */}
            <div>
              <label
                htmlFor="label-description"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                {t('labels.description_field', 'Beschreibung')}
              </label>
              <textarea
                id="label-description"
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder={t(
                  'labels.description_placeholder',
                  'Optionale Beschreibung des Labels...',
                )}
                maxLength={500}
                rows={2}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newName.trim() || isCreating}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreating ? (
                  <span className="flex items-center gap-1.5">
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    {t('labels.creating', 'Wird erstellt...')}
                  </span>
                ) : (
                  t('labels.create_submit', 'Label erstellen')
                )}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false);
                  setNewName('');
                  setNewColor('#3B82F6');
                  setNewDescription('');
                }}
                className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
              >
                {t('common:cancel', 'Abbrechen')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Active Labels List */}
      {activeLabels.length === 0 && !showCreateForm ? (
        <div className="rounded-lg border-2 border-dashed border-neutral-200 py-8 text-center">
          <p className="text-sm text-neutral-500">
            {t(
              'labels.empty',
              'Noch keine Labels vorhanden. Erstellen Sie Ihr erstes Label.',
            )}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
          {activeLabels.map((label) => (
            <div
              key={label.id}
              className="flex items-center justify-between px-4 py-3"
            >
              {editingId === label.id ? (
                /* ── Inline Edit Form ─────────────────────────── */
                <div className="flex-1 space-y-3">
                  <div className="flex items-center gap-3">
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      maxLength={100}
                      className="flex-1 rounded-md border border-neutral-300 px-3 py-1.5 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                      autoFocus
                    />
                  </div>
                  <ColorPicker value={editColor} onChange={setEditColor} />
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder={t(
                      'labels.description_placeholder',
                      'Optionale Beschreibung des Labels...',
                    )}
                    maxLength={500}
                    rows={2}
                    className="w-full rounded-md border border-neutral-300 px-3 py-1.5 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  {/* Edit Preview */}
                  {editName.trim() && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-neutral-500">
                        {t('labels.preview', 'Vorschau:')}
                      </span>
                      <LabelBadge name={editName.trim()} color={editColor} />
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleUpdate}
                      disabled={!editName.trim() || isUpdating}
                      className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isUpdating ? (
                        <span className="flex items-center gap-1.5">
                          <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                          {t('labels.saving', 'Wird gespeichert...')}
                        </span>
                      ) : (
                        t('common:save', 'Speichern')
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
                    >
                      {t('common:cancel', 'Abbrechen')}
                    </button>
                  </div>
                </div>
              ) : (
                /* ── Display Mode ─────────────────────────────── */
                <>
                  <div className="flex items-center gap-3">
                    <LabelBadge name={label.name} color={label.color} size="md" />
                    {label.description && (
                      <span className="text-xs text-neutral-400">
                        {label.description}
                      </span>
                    )}
                  </div>

                  {canEdit && (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => startEdit(label)}
                        className="rounded-md p-1.5 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                        aria-label={t('labels.edit', 'Label bearbeiten')}
                      >
                        <svg
                          className="h-4 w-4"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                          />
                        </svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(label.id)}
                        className="rounded-md p-1.5 text-neutral-400 transition-colors hover:bg-danger/10 hover:text-danger"
                        aria-label={t('labels.deactivate', 'Label deaktivieren')}
                      >
                        <svg
                          className="h-4 w-4"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
                          />
                        </svg>
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Inactive Labels Section */}
      {inactiveLabels.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-neutral-500">
            {t('labels.inactive_title', 'Deaktivierte Labels')} ({inactiveLabels.length})
          </h4>
          <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-neutral-50">
            {inactiveLabels.map((label) => (
              <div
                key={label.id}
                className="flex items-center justify-between px-4 py-2.5 opacity-60"
              >
                <div className="flex items-center gap-3">
                  <LabelBadge name={label.name} color={label.color} />
                  <span className="text-xs italic text-neutral-400">
                    {t('labels.inactive_badge', 'deaktiviert')}
                  </span>
                </div>

                {canEdit && (
                  <button
                    type="button"
                    onClick={() => handleReactivate(label.id)}
                    className="rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                  >
                    {t('labels.reactivate', 'Reaktivieren')}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
