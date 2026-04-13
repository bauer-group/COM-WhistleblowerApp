/**
 * Hinweisgebersystem - StepIndicator Component.
 *
 * 3-step wizard progress bar for the report submission flow.
 * Steps: 1) Category selection, 2) Description & files, 3) Review & submit.
 *
 * WCAG 2.1 AA compliant:
 * - Uses aria-current="step" on the active step
 * - aria-label on the navigation for screen readers
 * - Semantic <ol> with numbered steps
 * - 4.5:1 contrast ratio on all states
 * - Responsive down to 320px min width
 */

import { useTranslation } from 'react-i18next';

export interface StepIndicatorStep {
  /** Translation key for the step label. */
  labelKey: string;
  /** Optional description translation key. */
  descriptionKey?: string;
}

interface StepIndicatorProps {
  /** Zero-based index of the current active step. */
  currentStep: number;
  /** Step definitions with i18n label keys. */
  steps: StepIndicatorStep[];
}

/**
 * Default 3-step wizard configuration for report submission.
 * Can be overridden by passing custom steps.
 */
export const DEFAULT_REPORT_STEPS: StepIndicatorStep[] = [
  { labelKey: 'report.steps.category', descriptionKey: 'report.steps.category_desc' },
  { labelKey: 'report.steps.details', descriptionKey: 'report.steps.details_desc' },
  { labelKey: 'report.steps.review', descriptionKey: 'report.steps.review_desc' },
];

type StepState = 'completed' | 'current' | 'upcoming';

function getStepState(index: number, currentStep: number): StepState {
  if (index < currentStep) return 'completed';
  if (index === currentStep) return 'current';
  return 'upcoming';
}

const stepStyles: Record<StepState, { circle: string; label: string; connector: string }> = {
  completed: {
    circle: 'bg-primary text-white border-primary',
    label: 'text-primary font-medium',
    connector: 'bg-primary',
  },
  current: {
    circle: 'bg-white text-primary border-primary ring-2 ring-primary ring-offset-2',
    label: 'text-neutral-900 font-semibold',
    connector: 'bg-neutral-300',
  },
  upcoming: {
    circle: 'bg-white text-neutral-400 border-neutral-300',
    label: 'text-neutral-500',
    connector: 'bg-neutral-300',
  },
};

export default function StepIndicator({
  currentStep,
  steps,
}: StepIndicatorProps) {
  const { t } = useTranslation('report');

  return (
    <nav aria-label={t('steps.nav_label', 'Fortschritt')} className="w-full">
      <ol className="flex items-center justify-between" role="list">
        {steps.map((step, index) => {
          const state = getStepState(index, currentStep);
          const styles = stepStyles[state];
          const isLast = index === steps.length - 1;

          return (
            <li
              key={step.labelKey}
              className={`flex items-center ${isLast ? '' : 'flex-1'}`}
              aria-current={state === 'current' ? 'step' : undefined}
            >
              <div className="flex flex-col items-center">
                {/* Step circle */}
                <div
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm transition-colors ${styles.circle}`}
                  aria-hidden="true"
                >
                  {state === 'completed' ? (
                    <svg
                      className="h-5 w-5"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                      aria-hidden="true"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  ) : (
                    index + 1
                  )}
                </div>

                {/* Step label */}
                <span
                  className={`mt-2 text-center text-xs sm:text-sm ${styles.label}`}
                >
                  <span className="sr-only">
                    {state === 'completed'
                      ? t('steps.completed', 'Abgeschlossen')
                      : state === 'current'
                        ? t('steps.current', 'Aktueller Schritt')
                        : t('steps.upcoming', 'Ausstehend')}
                    {': '}
                  </span>
                  {t(step.labelKey)}
                </span>

                {/* Step description (visible on larger screens) */}
                {step.descriptionKey && (
                  <span className="mt-0.5 hidden text-center text-xs text-neutral-500 sm:block">
                    {t(step.descriptionKey)}
                  </span>
                )}
              </div>

              {/* Connector line between steps */}
              {!isLast && (
                <div
                  className={`mx-2 h-0.5 flex-1 transition-colors sm:mx-4 ${styles.connector}`}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
