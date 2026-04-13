/**
 * Hinweisgebersystem – SubStatusManager Component.
 *
 * Full CRUD management UI for tenant-scoped case sub-statuses.
 * Sub-statuses are configurable refinements of the five fixed
 * HinSchG lifecycle statuses (e.g. "Waiting for external input"
 * under ``in_bearbeitung``).
 *
 * Provides:
 * - Parent status tabs for navigating between lifecycle stages
 * - List of existing sub-statuses per parent status with inline editing
 * - Creation form with name, display order, and default flag
 * - Soft-delete (deactivate) and reactivation
 *
 * Designed to be embedded in the Settings page as a tab panel.
 * Uses the sub-statuses API client for all server communication.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ReportStatus } from '@/api/cases';
import type {
  SubStatusCreateRequest,
  SubStatusResponse,
  SubStatusUpdateRequest,
} from '@/api/substatuses';
import {
  getSubStatuses,
  createSubStatus,
  updateSubStatus,
  deleteSubStatus,
} from '@/api/substatuses';

// ── Types ─────────────────────────────────────────────────────

interface SubStatusManagerProps {
  /** Whether the user has permission to create/edit sub-statuses. */
  canEdit?: boolean;
}

// ── Parent Status Definitions ─────────────────────────────────

const PARENT_STATUSES: { value: ReportStatus; labelKey: string; fallback: string }[] = [
  { value: 'eingegangen', labelKey: 'common:status.eingegangen', fallback: 'Eingegangen' },
  { value: 'in_pruefung', labelKey: 'common:status.in_pruefung', fallback: 'In Prüfung' },
  { value: 'in_bearbeitung', labelKey: 'common:status.in_bearbeitung', fallback: 'In Bearbeitung' },
  { value: 'rueckmeldung', labelKey: 'common:status.rueckmeldung', fallback: 'Rückmeldung' },
  { value: 'abgeschlossen', labelKey: 'common:status.abgeschlossen', fallback: 'Abgeschlossen' },
];

// ── Component ────────────────────────────────────────────────

/**
 * Sub-status management UI with CRUD operations grouped by parent status.
 *
 * Renders tabs for each parent status and within each tab a list of
 * existing sub-statuses with edit/deactivate controls and a form for
 * creating new sub-statuses.
 */
export default function SubStatusManager({ canEdit = true }: SubStatusManagerProps) {
  const { t } = useTranslation('admin');

  // ── State ──────────────────────────────────────────────────
  const [activeParentStatus, setActiveParentStatus] = useState<ReportStatus>('eingegangen');
  const [subStatuses, setSubStatuses] = useState<SubStatusResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDisplayOrder, setNewDisplayOrder] = useState(0);
  const [newIsDefault, setNewIsDefault] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editDisplayOrder, setEditDisplayOrder] = useState(0);
  const [editIsDefault, setEditIsDefault] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  // ── Fetch Sub-Statuses ────────────────────────────────────

  const fetchSubStatuses = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await getSubStatuses({
        parent_status: activeParentStatus,
        page_size: 100,
      });
      setSubStatuses(response.items);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t('sub_statuses.error.load', 'Fehler beim Laden der Unterstatus.'),
      );
    } finally {
      setIsLoading(false);
    }
  }, [activeParentStatus, t]);

  useEffect(() => {
    fetchSubStatuses();
  }, [fetchSubStatuses]);

  // Reset create form when switching parent status
  useEffect(() => {
    setShowCreateForm(false);
    setNewName('');
    setNewDisplayOrder(0);
    setNewIsDefault(false);
    setEditingId(null);
  }, [activeParentStatus]);

  // ── Create Handler ─────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;

    setIsCreating(true);
    setError(null);

    try {
      const data: SubStatusCreateRequest = {
        parent_status: activeParentStatus,
        name: newName.trim(),
        display_order: newDisplayOrder,
        is_default: newIsDefault,
      };

      const created = await createSubStatus(data);

      // If this was set as default, update existing items
      if (created.is_default) {
        setSubStatuses((prev) =>
          prev.map((ss) =>
            ss.id !== created.id ? { ...ss, is_default: false } : ss,
          ),
        );
      }

      setSubStatuses((prev) => [...prev, created]);
      setNewName('');
      setNewDisplayOrder(0);
      setNewIsDefault(false);
      setShowCreateForm(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes('409')) {
        setError(
          t(
            'sub_statuses.error.duplicate',
            'Ein Unterstatus mit diesem Namen existiert bereits für diesen Hauptstatus.',
          ),
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : t('sub_statuses.error.create', 'Fehler beim Erstellen des Unterstatus.'),
        );
      }
    } finally {
      setIsCreating(false);
    }
  }, [newName, newDisplayOrder, newIsDefault, activeParentStatus, t]);

  // ── Edit Handlers ──────────────────────────────────────────

  const startEdit = useCallback((subStatus: SubStatusResponse) => {
    setEditingId(subStatus.id);
    setEditName(subStatus.name);
    setEditDisplayOrder(subStatus.display_order);
    setEditIsDefault(subStatus.is_default);
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditName('');
    setEditDisplayOrder(0);
    setEditIsDefault(false);
  }, []);

  const handleUpdate = useCallback(async () => {
    if (!editingId || !editName.trim()) return;

    setIsUpdating(true);
    setError(null);

    try {
      const data: SubStatusUpdateRequest = {
        name: editName.trim(),
        display_order: editDisplayOrder,
        is_default: editIsDefault,
      };

      const updated = await updateSubStatus(editingId, data);

      // If this was set as default, update existing items
      if (updated.is_default) {
        setSubStatuses((prev) =>
          prev.map((ss) =>
            ss.id === editingId
              ? updated
              : { ...ss, is_default: false },
          ),
        );
      } else {
        setSubStatuses((prev) =>
          prev.map((ss) => (ss.id === editingId ? updated : ss)),
        );
      }

      cancelEdit();
    } catch (err) {
      if (err instanceof Error && err.message.includes('409')) {
        setError(
          t(
            'sub_statuses.error.duplicate',
            'Ein Unterstatus mit diesem Namen existiert bereits für diesen Hauptstatus.',
          ),
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : t('sub_statuses.error.update', 'Fehler beim Aktualisieren des Unterstatus.'),
        );
      }
    } finally {
      setIsUpdating(false);
    }
  }, [editingId, editName, editDisplayOrder, editIsDefault, cancelEdit, t]);

  // ── Delete (Deactivate) Handler ────────────────────────────

  const handleDelete = useCallback(
    async (subStatusId: string) => {
      setError(null);

      try {
        await deleteSubStatus(subStatusId);
        setSubStatuses((prev) =>
          prev.map((ss) =>
            ss.id === subStatusId ? { ...ss, is_active: false } : ss,
          ),
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('sub_statuses.error.delete', 'Fehler beim Deaktivieren des Unterstatus.'),
        );
      }
    },
    [t],
  );

  // ── Reactivate Handler ─────────────────────────────────────

  const handleReactivate = useCallback(
    async (subStatusId: string) => {
      setError(null);

      try {
        const updated = await updateSubStatus(subStatusId, { is_active: true });
        setSubStatuses((prev) =>
          prev.map((ss) => (ss.id === subStatusId ? updated : ss)),
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t('sub_statuses.error.update', 'Fehler beim Aktualisieren des Unterstatus.'),
        );
      }
    },
    [t],
  );

  // ── Derived Data ───────────────────────────────────────────

  const activeItems = subStatuses.filter((ss) => ss.is_active);
  const inactiveItems = subStatuses.filter((ss) => !ss.is_active);

  // ── Render ─────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Parent Status Tabs */}
      <div className="border-b border-neutral-200">
        <nav className="-mb-px flex gap-2 overflow-x-auto" role="tablist" aria-label={t('sub_statuses.parent_status_tabs', 'Hauptstatus')}>
          {PARENT_STATUSES.map((ps) => (
            <button
              key={ps.value}
              type="button"
              role="tab"
              aria-selected={activeParentStatus === ps.value}
              onClick={() => setActiveParentStatus(ps.value)}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                activeParentStatus === ps.value
                  ? 'border-primary text-primary'
                  : 'border-transparent text-neutral-500 hover:border-neutral-300 hover:text-neutral-700'
              }`}
            >
              {t(ps.labelKey, ps.fallback)}
            </button>
          ))}
        </nav>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-neutral-500">
            {t(
              'sub_statuses.panel_description',
              'Unterstatus für diesen Hauptstatus verwalten.',
            )}
          </p>
        </div>

        {canEdit && !showCreateForm && (
          <button
            type="button"
            onClick={() => setShowCreateForm(true)}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
          >
            {t('sub_statuses.create_button', 'Neuer Unterstatus')}
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
            {t('sub_statuses.create_title', 'Neuen Unterstatus erstellen')}
          </h4>

          <div className="space-y-3">
            {/* Name Input */}
            <div>
              <label
                htmlFor="substatus-name"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                {t('sub_statuses.name', 'Name')} *
              </label>
              <input
                id="substatus-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t(
                  'sub_statuses.name_placeholder',
                  'z.B. Warten auf externe Rückmeldung...',
                )}
                maxLength={255}
                className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                autoFocus
              />
            </div>

            {/* Display Order */}
            <div>
              <label
                htmlFor="substatus-order"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                {t('sub_statuses.display_order', 'Anzeigereihenfolge')}
              </label>
              <input
                id="substatus-order"
                type="number"
                min={0}
                value={newDisplayOrder}
                onChange={(e) => setNewDisplayOrder(Number(e.target.value))}
                className="w-32 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <p className="mt-1 text-xs text-neutral-500">
                {t('sub_statuses.display_order_hint', 'Niedrigere Werte werden zuerst angezeigt.')}
              </p>
            </div>

            {/* Default Flag */}
            <div className="flex items-center gap-2">
              <input
                id="substatus-default"
                type="checkbox"
                checked={newIsDefault}
                onChange={(e) => setNewIsDefault(e.target.checked)}
                className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
              />
              <label htmlFor="substatus-default" className="text-sm font-medium text-neutral-700">
                {t('sub_statuses.is_default', 'Als Standard festlegen')}
              </label>
              <span className="text-xs text-neutral-400">
                {t(
                  'sub_statuses.is_default_hint',
                  '(wird automatisch zugewiesen bei Statuswechsel)',
                )}
              </span>
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
                    {t('sub_statuses.creating', 'Wird erstellt...')}
                  </span>
                ) : (
                  t('sub_statuses.create_submit', 'Unterstatus erstellen')
                )}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateForm(false);
                  setNewName('');
                  setNewDisplayOrder(0);
                  setNewIsDefault(false);
                }}
                className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
              >
                {t('common:cancel', 'Abbrechen')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading State */}
      {isLoading ? (
        <div
          className="flex items-center justify-center py-12"
          role="status"
          aria-label={t('sub_statuses.loading', 'Unterstatus werden geladen...')}
        >
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Active Sub-Statuses List */}
          {activeItems.length === 0 && !showCreateForm ? (
            <div className="rounded-lg border-2 border-dashed border-neutral-200 py-8 text-center">
              <p className="text-sm text-neutral-500">
                {t(
                  'sub_statuses.empty',
                  'Keine Unterstatus für diesen Hauptstatus vorhanden.',
                )}
              </p>
            </div>
          ) : (
            activeItems.length > 0 && (
              <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
                {activeItems.map((subStatus) => (
                  <div
                    key={subStatus.id}
                    className="flex items-center justify-between px-4 py-3"
                  >
                    {editingId === subStatus.id ? (
                      /* ── Inline Edit Form ─────────────────────────── */
                      <div className="flex-1 space-y-3">
                        <div>
                          <label
                            htmlFor={`edit-name-${subStatus.id}`}
                            className="mb-1 block text-xs font-medium text-neutral-600"
                          >
                            {t('sub_statuses.name', 'Name')}
                          </label>
                          <input
                            id={`edit-name-${subStatus.id}`}
                            type="text"
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            maxLength={255}
                            className="w-full rounded-md border border-neutral-300 px-3 py-1.5 text-sm transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                            autoFocus
                          />
                        </div>
                        <div className="flex items-center gap-4">
                          <div>
                            <label
                              htmlFor={`edit-order-${subStatus.id}`}
                              className="mb-1 block text-xs font-medium text-neutral-600"
                            >
                              {t('sub_statuses.display_order', 'Anzeigereihenfolge')}
                            </label>
                            <input
                              id={`edit-order-${subStatus.id}`}
                              type="number"
                              min={0}
                              value={editDisplayOrder}
                              onChange={(e) => setEditDisplayOrder(Number(e.target.value))}
                              className="w-24 rounded-md border border-neutral-300 px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                            />
                          </div>
                          <div className="flex items-center gap-2 pt-5">
                            <input
                              id={`edit-default-${subStatus.id}`}
                              type="checkbox"
                              checked={editIsDefault}
                              onChange={(e) => setEditIsDefault(e.target.checked)}
                              className="h-4 w-4 rounded border-neutral-300 text-primary focus:ring-primary"
                            />
                            <label
                              htmlFor={`edit-default-${subStatus.id}`}
                              className="text-sm font-medium text-neutral-700"
                            >
                              {t('sub_statuses.is_default', 'Als Standard festlegen')}
                            </label>
                          </div>
                        </div>
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
                                {t('sub_statuses.saving', 'Wird gespeichert...')}
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
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-neutral-100 text-xs font-medium text-neutral-600">
                            {subStatus.display_order}
                          </span>
                          <span className="text-sm font-medium text-neutral-900">
                            {subStatus.name}
                          </span>
                          {subStatus.is_default && (
                            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                              {t('sub_statuses.default_badge', 'Standard')}
                            </span>
                          )}
                        </div>

                        {canEdit && (
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => startEdit(subStatus)}
                              className="rounded-md p-1.5 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                              aria-label={t('sub_statuses.edit', 'Unterstatus bearbeiten')}
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
                              onClick={() => handleDelete(subStatus.id)}
                              className="rounded-md p-1.5 text-neutral-400 transition-colors hover:bg-danger/10 hover:text-danger"
                              aria-label={t('sub_statuses.deactivate', 'Unterstatus deaktivieren')}
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
            )
          )}

          {/* Inactive Sub-Statuses Section */}
          {inactiveItems.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-medium text-neutral-500">
                {t('sub_statuses.inactive_title', 'Deaktivierte Unterstatus')} ({inactiveItems.length})
              </h4>
              <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-neutral-50">
                {inactiveItems.map((subStatus) => (
                  <div
                    key={subStatus.id}
                    className="flex items-center justify-between px-4 py-2.5 opacity-60"
                  >
                    <div className="flex items-center gap-3">
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-neutral-100 text-xs font-medium text-neutral-400">
                        {subStatus.display_order}
                      </span>
                      <span className="text-sm text-neutral-600">
                        {subStatus.name}
                      </span>
                      <span className="text-xs italic text-neutral-400">
                        {t('sub_statuses.inactive_badge', 'deaktiviert')}
                      </span>
                    </div>

                    {canEdit && (
                      <button
                        type="button"
                        onClick={() => handleReactivate(subStatus.id)}
                        className="rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                      >
                        {t('sub_statuses.reactivate', 'Reaktivieren')}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
