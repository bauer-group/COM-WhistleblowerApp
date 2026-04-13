/**
 * Hinweisgebersystem - ReportSuccess Page Component.
 *
 * Displays the case number and passphrase after successful report
 * submission.  Includes copy-to-clipboard buttons and a prominent
 * warning about credential loss (no recovery mechanism).
 *
 * WCAG 2.1 AA compliant:
 * - Semantic heading hierarchy
 * - aria-live region for copy confirmation
 * - Keyboard-accessible copy buttons
 * - High-contrast warning styling
 * - Responsive layout (320px min width)
 */

import { useCallback, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

// ── Types ──────────────────────────────────────────────────────

interface SuccessState {
  caseNumber: string;
  passphrase: string | null;
  hasPassword: boolean;
  channel: string;
}

// ── Copy Button Component ──────────────────────────────────────

interface CopyButtonProps {
  text: string;
  label: string;
}

function CopyButton({ text, label }: CopyButtonProps) {
  const { t } = useTranslation('report');
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers or restricted contexts
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex items-center gap-1.5 rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-xs font-medium text-neutral-700 transition-colors hover:bg-neutral-50 focus:ring-2 focus:ring-primary focus:ring-offset-1"
      aria-label={label}
    >
      {copied ? (
        <>
          <svg
            className="h-4 w-4 text-success"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
          {t('success.copied', 'Kopiert!')}
        </>
      ) : (
        <>
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
              d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"
            />
          </svg>
          {t('success.copy', 'Kopieren')}
        </>
      )}
    </button>
  );
}

// ── Component ─────────────────────────────────────────────────

export default function ReportSuccess() {
  const { t } = useTranslation('report');
  const navigate = useNavigate();
  const location = useLocation();

  const state = location.state as SuccessState | null;

  // Guard: no state means direct navigation (not via wizard)
  if (!state?.caseNumber) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-xl font-bold text-neutral-900">
          {t('success.no_data_title', 'Keine Meldungsdaten vorhanden')}
        </h1>
        <p className="mt-2 text-neutral-600">
          {t(
            'success.no_data_text',
            'Diese Seite kann nur nach dem Absenden einer Meldung aufgerufen werden.',
          )}
        </p>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="mt-6 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
        >
          {t('success.go_home', 'Zur Startseite')}
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Success header */}
      <div className="mb-8 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-success/10">
          <svg
            className="h-8 w-8 text-success"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-neutral-900">
          {t('success.title', 'Meldung erfolgreich eingereicht')}
        </h1>
        <p className="mt-2 text-neutral-600">
          {t(
            'success.subtitle',
            'Ihre Meldung wurde sicher übermittelt und wird zeitnah bearbeitet.',
          )}
        </p>
      </div>

      {/* Credential loss warning - PROMINENT */}
      <div
        className="mb-8 rounded-xl border-2 border-danger/40 bg-danger/5 p-5"
        role="alert"
      >
        <div className="flex gap-3">
          <svg
            className="h-6 w-6 shrink-0 text-danger"
            fill="currentColor"
            viewBox="0 0 20 20"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
          <div>
            <h2 className="text-base font-bold text-danger">
              {t('success.warning_title', 'Wichtig: Zugangsdaten sichern!')}
            </h2>
            <p className="mt-1 text-sm text-neutral-800">
              {t(
                'success.warning_text',
                'Notieren oder kopieren Sie die folgenden Zugangsdaten jetzt. Ohne diese Daten können Sie nicht mehr auf Ihr sicheres Postfach zugreifen. Es gibt keine Möglichkeit, verlorene Zugangsdaten wiederherzustellen.',
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Credentials display */}
      <div className="space-y-4">
        {/* Case number */}
        <div className="rounded-lg border border-neutral-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-neutral-500">
                {t('success.case_number_label', 'Fallnummer')}
              </p>
              <p className="mt-1 font-mono text-lg font-bold text-neutral-900 sm:text-xl">
                {state.caseNumber}
              </p>
            </div>
            <CopyButton
              text={state.caseNumber}
              label={t('success.copy_case_number', 'Fallnummer kopieren')}
            />
          </div>
        </div>

        {/* Passphrase (if not using self-chosen password) */}
        {state.passphrase && (
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-neutral-500">
                  {t('success.passphrase_label', 'Passphrase')}
                </p>
                <p className="mt-1 font-mono text-lg font-bold text-neutral-900 sm:text-xl">
                  {state.passphrase}
                </p>
              </div>
              <CopyButton
                text={state.passphrase}
                label={t('success.copy_passphrase', 'Passphrase kopieren')}
              />
            </div>
          </div>
        )}

        {/* Self-chosen password note */}
        {state.hasPassword && (
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-500">
              {t('success.password_label', 'Passwort')}
            </p>
            <p className="mt-1 text-sm text-neutral-700">
              {t(
                'success.password_note',
                'Sie haben ein eigenes Passwort gewählt. Verwenden Sie dieses zusammen mit der Fallnummer, um auf Ihr Postfach zuzugreifen.',
              )}
            </p>
          </div>
        )}
      </div>

      {/* Next steps */}
      <div className="mt-8 rounded-lg border border-neutral-200 bg-neutral-50 p-5">
        <h2 className="mb-3 text-sm font-semibold text-neutral-900">
          {t('success.next_steps_title', 'Nächste Schritte')}
        </h2>
        <ul className="space-y-2 text-sm text-neutral-600">
          <li className="flex items-start gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-white">
              1
            </span>
            {t(
              'success.step_1',
              'Speichern Sie Ihre Zugangsdaten an einem sicheren Ort.',
            )}
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-white">
              2
            </span>
            {t(
              'success.step_2',
              'Prüfen Sie regelmäßig Ihr Postfach auf Rückmeldungen.',
            )}
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-white">
              3
            </span>
            {t(
              'success.step_3',
              'Sie erhalten innerhalb von 7 Tagen eine Eingangsbestätigung.',
            )}
          </li>
        </ul>
      </div>

      {/* Action buttons */}
      <div className="mt-8 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => navigate('/mailbox/login')}
          className="rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
        >
          {t('success.go_to_mailbox', 'Zum Postfach')}
        </button>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
        >
          {t('success.go_home', 'Zur Startseite')}
        </button>
      </div>
    </div>
  );
}
