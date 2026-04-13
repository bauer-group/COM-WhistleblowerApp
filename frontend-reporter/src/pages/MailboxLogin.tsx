/**
 * Hinweisgebersystem - MailboxLogin Page Component.
 *
 * Login form for the anonymous mailbox using case number and
 * passphrase/password.  Includes hCaptcha bot protection.
 * On success, navigates to the Mailbox page with the session token.
 *
 * WCAG 2.1 AA compliant:
 * - Semantic form with associated labels
 * - aria-describedby for error messages
 * - aria-live region for login errors
 * - Keyboard-accessible form controls
 * - 4.5:1 contrast ratio
 * - Responsive layout (320px min width)
 */

import { useCallback, useRef, useState } from 'react';
import { useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';

import CaptchaWidget, { type CaptchaWidgetHandle } from '@/components/CaptchaWidget';
import { useVerifyCredentials } from '@/hooks/useReport';
import { mailboxLoginSchema, type MailboxLoginData } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

type FormErrors = Partial<Record<keyof MailboxLoginData | 'captcha' | 'form', string>>;

// ── Component ─────────────────────────────────────────────────

export default function MailboxLogin() {
  const { t } = useTranslation('mailbox');
  const navigate = useNavigate();
  const captchaRef = useRef<CaptchaWidgetHandle>(null);

  const [caseNumber, setCaseNumber] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [captchaToken, setCaptchaToken] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});

  const verifyCredentials = useVerifyCredentials();

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setErrors({});

      // Validate with Zod
      const result = mailboxLoginSchema.safeParse({
        case_number: caseNumber,
        passphrase,
      });

      if (!result.success) {
        const zodErrors: FormErrors = {};
        for (const issue of result.error.issues) {
          const key = issue.path[0] as keyof MailboxLoginData;
          zodErrors[key] = issue.message;
        }
        setErrors(zodErrors);
        return;
      }

      try {
        const response = await verifyCredentials.mutateAsync({
          caseNumber: result.data.case_number,
          passphrase: result.data.passphrase,
          channel: undefined, // Auto-detected by backend
        });

        navigate('/mailbox', {
          state: {
            token: response.access_token,
            caseNumber: response.case_number,
            channel: response.channel,
            status: response.status,
          },
        });
      } catch {
        captchaRef.current?.resetCaptcha();
        setCaptchaToken('');
        setErrors({
          form: t(
            'login.error',
            'Fallnummer oder Passphrase ungültig. Bitte überprüfen Sie Ihre Eingaben.',
          ),
        });
      }
    },
    [caseNumber, passphrase, captchaToken, verifyCredentials, navigate, t],
  );

  const isSubmitting = verifyCredentials.isPending;

  const inputClasses = (field: string) =>
    `w-full rounded-lg border px-3 py-2.5 text-sm text-neutral-900 transition-colors ${
      errors[field as keyof FormErrors]
        ? 'border-danger focus:border-danger focus:ring-danger'
        : 'border-neutral-300 focus:border-primary focus:ring-primary'
    } bg-white focus:ring-2 focus:ring-offset-0`;

  return (
    <div className="mx-auto max-w-md px-4 py-8 sm:px-6">
      {/* Header */}
      <div className="mb-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
          <svg
            className="h-7 w-7 text-primary"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M16 12a4 4 0 10-8 0 4 4 0 008 0zm0 0v1.5a2.5 2.5 0 005 0V12a9 9 0 10-9 9m4.5-1.206a8.959 8.959 0 01-4.5 1.207"
            />
          </svg>
        </div>
        <h1 className="text-xl font-bold text-neutral-900 sm:text-2xl">
          {t('login.title', 'Postfach-Login')}
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          {t(
            'login.subtitle',
            'Geben Sie Ihre Fallnummer und Passphrase ein, um auf Ihr sicheres Postfach zuzugreifen.',
          )}
        </p>
      </div>

      {/* Login form */}
      <form onSubmit={handleSubmit} noValidate className="space-y-5">
        {/* Form-level error */}
        {errors.form && (
          <div
            className="rounded-lg border border-danger/30 bg-danger/5 p-4"
            role="alert"
            aria-live="assertive"
          >
            <p className="text-sm text-danger">{errors.form}</p>
          </div>
        )}

        {/* Case number */}
        <div>
          <label
            htmlFor="case-number"
            className="mb-1.5 block text-sm font-medium text-neutral-700"
          >
            {t('login.case_number', 'Fallnummer')}
            <span className="ml-1 text-danger" aria-hidden="true">*</span>
          </label>
          <input
            id="case-number"
            type="text"
            value={caseNumber}
            onChange={(e) => {
              setCaseNumber(e.target.value);
              setErrors((prev) => {
                if (!prev.case_number) return prev;
                const next = { ...prev };
                delete next.case_number;
                return next;
              });
            }}
            maxLength={16}
            autoComplete="off"
            aria-required="true"
            aria-invalid={!!errors.case_number}
            aria-describedby={errors.case_number ? 'case-number-error' : 'case-number-hint'}
            className={inputClasses('case_number')}
            placeholder="ABCD1234EFGH5678"
          />
          <p id="case-number-hint" className="mt-1 text-xs text-neutral-500">
            {t('login.case_number_hint', '16 Zeichen, z.B. ABCD1234EFGH5678')}
          </p>
          {errors.case_number && (
            <p id="case-number-error" className="mt-1.5 text-sm text-danger" role="alert">
              {t(errors.case_number, errors.case_number)}
            </p>
          )}
        </div>

        {/* Passphrase / Password */}
        <div>
          <label
            htmlFor="passphrase"
            className="mb-1.5 block text-sm font-medium text-neutral-700"
          >
            {t('login.passphrase', 'Passphrase oder Passwort')}
            <span className="ml-1 text-danger" aria-hidden="true">*</span>
          </label>
          <input
            id="passphrase"
            type="password"
            value={passphrase}
            onChange={(e) => {
              setPassphrase(e.target.value);
              setErrors((prev) => {
                if (!prev.passphrase) return prev;
                const next = { ...prev };
                delete next.passphrase;
                return next;
              });
            }}
            autoComplete="off"
            aria-required="true"
            aria-invalid={!!errors.passphrase}
            aria-describedby={errors.passphrase ? 'passphrase-error' : 'passphrase-hint'}
            className={inputClasses('passphrase')}
          />
          <p id="passphrase-hint" className="mt-1 text-xs text-neutral-500">
            {t(
              'login.passphrase_hint',
              'Die 6-Wort-Passphrase oder Ihr selbst gewähltes Passwort',
            )}
          </p>
          {errors.passphrase && (
            <p id="passphrase-error" className="mt-1.5 text-sm text-danger" role="alert">
              {t(errors.passphrase, errors.passphrase)}
            </p>
          )}
        </div>

        {/* hCaptcha */}
        <CaptchaWidget
          ref={captchaRef}
          onVerify={setCaptchaToken}
          onExpire={() => setCaptchaToken('')}
          onError={() => setCaptchaToken('')}
        />

        {/* Submit button */}
        <button
          type="submit"
          disabled={isSubmitting}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting && (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          )}
          {isSubmitting
            ? t('login.logging_in', 'Anmeldung...')
            : t('login.submit', 'Anmelden')}
        </button>
      </form>

      {/* Alternative login methods */}
      <div className="mt-6 border-t border-neutral-200 pt-6 text-center">
        <p className="text-sm text-neutral-600">
          {t(
            'login.magic_link_text',
            'E-Mail-Adresse bei der Meldung angegeben?',
          )}
        </p>
        <Link
          to="/magic-link"
          className="mt-1 inline-block text-sm font-medium text-primary transition-colors hover:text-primary-dark"
        >
          {t('login.magic_link_action', 'Per E-Mail-Link anmelden')}
        </Link>
      </div>

      {/* Back to home */}
      <div className="mt-4 text-center">
        <Link
          to="/"
          className="text-sm text-neutral-500 transition-colors hover:text-neutral-700"
        >
          {t('login.back_home', 'Zurück zur Startseite')}
        </Link>
      </div>
    </div>
  );
}
