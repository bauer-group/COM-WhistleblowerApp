/**
 * Hinweisgebersystem – Visual Status Workflow Component.
 *
 * Displays the case lifecycle as a visual step indicator:
 *   Eingegangen → In Prüfung → In Bearbeitung → Rückmeldung → Abgeschlossen
 *
 * Each step shows its label, completion state, and transition controls.
 * The handler can advance or change the status via dropdown when permitted.
 * Status transitions are validated:
 *   - Forward transitions are always allowed
 *   - Backward transitions are allowed except from "abgeschlossen"
 *
 * When sub-statuses are defined for the current parent status, a
 * sub-status dropdown is shown below the workflow indicator.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ReportStatus } from '@/api/cases';
import type { SubStatusSummary } from '@/api/substatuses';

// ── Types ─────────────────────────────────────────────────────

interface StatusWorkflowProps {
  /** Current case status. */
  currentStatus: ReportStatus;
  /** Callback when the handler selects a new status. */
  onStatusChange: (newStatus: ReportStatus) => void;
  /** Whether a status update is currently in progress. */
  isUpdating?: boolean;
  /** Whether the user has permission to change status. */
  canEdit?: boolean;
  /** Currently selected sub-status ID (if any). */
  currentSubStatusId?: string | null;
  /** Available sub-statuses for the current parent status. */
  subStatuses?: SubStatusSummary[];
  /** Callback when the handler selects a new sub-status. */
  onSubStatusChange?: (subStatusId: string | null) => void;
}

// ── Status Step Definitions ──────────────────────────────────

interface StatusStep {
  value: ReportStatus;
  label: string;
  description: string;
}

const STATUS_INDEX: Record<ReportStatus, number> = {
  eingegangen: 0,
  in_pruefung: 1,
  in_bearbeitung: 2,
  rueckmeldung: 3,
  abgeschlossen: 4,
};

// ── Step State Helpers ───────────────────────────────────────

type StepState = 'completed' | 'current' | 'upcoming';

function getStepState(
  stepIndex: number,
  currentIndex: number,
): StepState {
  if (stepIndex < currentIndex) return 'completed';
  if (stepIndex === currentIndex) return 'current';
  return 'upcoming';
}

const STEP_STYLES: Record<
  StepState,
  { circle: string; label: string; connector: string }
> = {
  completed: {
    circle: 'bg-success text-white border-success',
    label: 'text-success font-medium',
    connector: 'bg-success',
  },
  current: {
    circle: 'bg-primary text-white border-primary ring-4 ring-primary/20',
    label: 'text-primary font-semibold',
    connector: 'bg-neutral-300',
  },
  upcoming: {
    circle: 'bg-white text-neutral-400 border-neutral-300',
    label: 'text-neutral-400',
    connector: 'bg-neutral-300',
  },
};

// ── Allowed Transitions ──────────────────────────────────────

/**
 * Determine which statuses the case can transition to from the current status.
 *
 * Rules:
 * - From any non-terminal status, can move forward to any subsequent status
 * - Can move backward except from "abgeschlossen"
 * - "abgeschlossen" can only be set, not reverted from
 */
function getAllowedTransitions(current: ReportStatus, steps: StatusStep[]): ReportStatus[] {
  if (current === 'abgeschlossen') {
    // Terminal status — no transitions allowed
    return [];
  }

  // Allow all statuses except the current one
  return steps
    .filter((step) => step.value !== current)
    .map((step) => step.value);
}

// ── Component ────────────────────────────────────────────────

/**
 * Visual status workflow indicator with transition controls.
 *
 * Renders a horizontal step indicator showing the case's position in the
 * lifecycle. If the user has edit permission, a dropdown allows selecting
 * a valid next status.
 */
export default function StatusWorkflow({
  currentStatus,
  onStatusChange,
  isUpdating = false,
  canEdit = true,
  currentSubStatusId = null,
  subStatuses = [],
  onSubStatusChange,
}: StatusWorkflowProps) {
  const { t } = useTranslation('cases');
  const [showTransition, setShowTransition] = useState(false);
  const currentIndex = STATUS_INDEX[currentStatus] ?? 0;

  const statusSteps = useMemo<StatusStep[]>(() => [
    { value: 'eingegangen', label: t('common:status.eingegangen', 'Eingegangen'), description: t('workflow.eingegangen_desc', 'Meldung wurde empfangen') },
    { value: 'in_pruefung', label: t('common:status.in_pruefung', 'In Prüfung'), description: t('workflow.in_pruefung_desc', 'Erstbewertung und Zuständigkeitsprüfung') },
    { value: 'in_bearbeitung', label: t('common:status.in_bearbeitung', 'In Bearbeitung'), description: t('workflow.in_bearbeitung_desc', 'Aktive Untersuchung und Sachverhaltsklärung') },
    { value: 'rueckmeldung', label: t('common:status.rueckmeldung', 'Rückmeldung'), description: t('workflow.rueckmeldung_desc', 'Ergebnis wird dem Hinweisgeber mitgeteilt') },
    { value: 'abgeschlossen', label: t('common:status.abgeschlossen', 'Abgeschlossen'), description: t('workflow.abgeschlossen_desc', 'Fall ist abschließend bearbeitet') },
  ], [t]);

  const allowedTransitions = useMemo(
    () => getAllowedTransitions(currentStatus, statusSteps),
    [currentStatus, statusSteps],
  );

  const handleStatusSelect = useCallback(
    (newStatus: ReportStatus) => {
      onStatusChange(newStatus);
      setShowTransition(false);
    },
    [onStatusChange],
  );

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-neutral-600">
          {t('workflow.title', 'Fallstatus')}
        </h3>

        {canEdit && allowedTransitions.length > 0 && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowTransition(!showTransition)}
              disabled={isUpdating}
              className="rounded-md border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
              aria-expanded={showTransition}
              aria-haspopup="listbox"
            >
              {isUpdating ? (
                <span className="flex items-center gap-1.5">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  {t('workflow.updating', 'Wird aktualisiert...')}
                </span>
              ) : (
                t('workflow.change_status', 'Status ändern')
              )}
            </button>

            {showTransition && (
              <div
                className="absolute right-0 z-10 mt-1 w-56 rounded-lg border border-neutral-200 bg-white py-1 shadow-lg"
                role="listbox"
                aria-label={t('workflow.select_status', 'Status auswählen')}
              >
                {allowedTransitions.map((status) => {
                  const step = statusSteps[STATUS_INDEX[status]];
                  return (
                    <button
                      key={status}
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => handleStatusSelect(status)}
                      className="flex w-full flex-col px-4 py-2 text-left transition-colors hover:bg-neutral-50"
                    >
                      <span className="text-sm font-medium text-neutral-900">
                        {step.label}
                      </span>
                      <span className="text-xs text-neutral-500">
                        {step.description}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Step Indicator */}
      <nav aria-label={t('workflow.progress_label', 'Fallstatus-Fortschritt')}>
        <ol className="flex items-center">
          {statusSteps.map((step, index) => {
            const state = getStepState(index, currentIndex);
            const styles = STEP_STYLES[state];
            const isLast = index === statusSteps.length - 1;

            return (
              <li
                key={step.value}
                className={`flex items-center ${isLast ? '' : 'flex-1'}`}
              >
                {/* Step Circle + Label */}
                <div className="flex flex-col items-center">
                  <div
                    className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs transition-all ${styles.circle}`}
                    aria-current={state === 'current' ? 'step' : undefined}
                  >
                    {state === 'completed' ? (
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
                          strokeWidth={3}
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    ) : (
                      <span>{index + 1}</span>
                    )}
                  </div>
                  <span
                    className={`mt-2 text-center text-xs leading-tight ${styles.label}`}
                  >
                    {step.label}
                  </span>
                </div>

                {/* Connector Line */}
                {!isLast && (
                  <div
                    className={`mx-2 h-0.5 flex-1 rounded-full transition-colors ${styles.connector}`}
                    aria-hidden="true"
                  />
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Sub-Status Dropdown */}
      {subStatuses.length > 0 && onSubStatusChange && (
        <div className="mt-4 border-t border-neutral-100 pt-4">
          <div className="flex items-center gap-3">
            <label
              htmlFor="sub-status-select"
              className="text-xs font-medium text-neutral-600"
            >
              {t('workflow.sub_status', 'Unterstatus')}
            </label>
            <select
              id="sub-status-select"
              value={currentSubStatusId ?? ''}
              onChange={(e) =>
                onSubStatusChange(e.target.value || null)
              }
              disabled={isUpdating || !canEdit}
              className="rounded-md border border-neutral-300 px-2 py-1 text-sm text-neutral-700 transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
              aria-label={t('workflow.select_sub_status', 'Unterstatus auswählen')}
            >
              <option value="">
                {t('workflow.no_sub_status', '— Kein Unterstatus —')}
              </option>
              {subStatuses.map((ss) => (
                <option key={ss.id} value={ss.id}>
                  {ss.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
