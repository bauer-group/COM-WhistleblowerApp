/**
 * Hinweisgebersystem - MagicLinkRequest Page Component.
 *
 * Email input form for requesting a magic link login.
 * Available to non-anonymous reporters who provided an email
 * address during report submission.
 *
 * Always shows a success message after submission, regardless of
 * whether the email was found (prevents user enumeration).
 *
 * WCAG 2.1 AA compliant:
 * - Semantic form with associated labels
 * - aria-describedby for error messages and hints
 * - aria-live region for status announcements
 * - Keyboard-accessible form controls
 * - 4.5:1 contrast ratio
 * - Responsive layout (320px min width)
 */

import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

import { useRequestMagicLink } from '@/hooks/useReport';
import { magicLinkRequestSchema, type MagicLinkRequestData } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

type FormErrors = Partial<Record<keyof MagicLinkRequestData | 'form', string>>;

// ── Component ─────────────────────────────────────────────────

export default function MagicLinkRequest() {
  const { t } = useTranslation('mailbox');

  const [caseNumber, setCaseNumber] = useState('');
  const [email, setEmail] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSuccess, setIsSuccess] = useState(false);

  const requestMagicLink = useRequestMagicLink();

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setErrors({});

      // Validate with Zod
      const result = magicLinkRequestSchema.safeParse({
        case_number: caseNumber,
        email,
      });

      if (!result.success) {
        const zodErrors: FormErrors = {};
        for (const issue of result.error.issues) {
          const key = issue.path[0] as keyof MagicLinkRequestData;
          zodErrors[key] = issue.message;
        }
        setErrors(zodErrors);
        return;
      }

      try {
        await requestMagicLink.mutateAsync({
          caseNumber: result.data.case_number,
          email: result.data.email,
        });
        // Always show success (prevents user enumeration)
        setIsSuccess(true);
      } catch {
        // Still show success to prevent enumeration
        setIsSuccess(true);
      }
    },
    [caseNumber, email, requestMagicLink],
  );

  const isSubmitting = requestMagicLink.isPending;

  const inputClasses = (field: string) =>
    `w-full rounded-lg border px-3 py-2.5 text-sm text-neutral-900 transition-colors ${
      errors[field as keyof FormErrors]
        ? 'border-danger focus:border-danger focus:ring-danger'
        : 'border-neutral-300 focus:border-primary focus:ring-primary'
    } bg-white focus:ring-2 focus:ring-offset-0`;

  // ── Success state ─────────────────────────────────────────

  if (isSuccess) {
    return (
      <div className="mx-auto max-w-md px-4 py-8 sm:px-6">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-success/10">
            <svg
              className="h-7 w-7 text-success"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-neutral-900" role="status">
            {t('magic_link.success_title', 'E-Mail versendet')}
          </h1>
          <p className="mt-2 text-sm text-neutral-600">
            {t(
              'magic_link.success_text',
              'Falls die angegebene E-Mail-Adresse mit einer Meldung verknüpft ist, erhalten Sie in Kürze einen Login-Link. Bitte prüfen Sie auch Ihren Spam-Ordner.',
            )}
          </p>
          <p className="mt-4 text-xs text-neutral-500">
            {t(
              'magic_link.success_expiry',
              'Der Link ist 15 Minuten gültig.',
            )}
          </p>
        </div>

        <div className="mt-8 flex flex-col gap-3 text-center">
          <Link
            to="/mailbox/login"
            className="inline-flex items-center justify-center rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
          >
            {t('magic_link.back_to_login', 'Zurück zum Login')}
          </Link>
          <Link
            to="/"
            className="text-sm text-neutral-500 transition-colors hover:text-neutral-700"
          >
            {t('magic_link.back_home', 'Zur Startseite')}
          </Link>
        </div>
      </div>
    );
  }

  // ── Form state ────────────────────────────────────────────

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
              d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
            />
          </svg>
        </div>
        <h1 className="text-xl font-bold text-neutral-900 sm:text-2xl">
          {t('magic_link.title', 'Login per E-Mail-Link')}
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          {t(
            'magic_link.subtitle',
            'Geben Sie Ihre Fallnummer und die E-Mail-Adresse ein, die Sie bei der Meldung angegeben haben.',
          )}
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} noValidate className="space-y-5">
        {/* Form-level error */}
        {errors.form && (
          <div
            className="rounded-lg border border-danger/30 bg-danger/5 p-4"
            role="alert"
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
            {t('magic_link.case_number', 'Fallnummer')}
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
            aria-describedby={errors.case_number ? 'case-number-error' : undefined}
            className={inputClasses('case_number')}
            placeholder="ABCD1234EFGH5678"
          />
          {errors.case_number && (
            <p id="case-number-error" className="mt-1.5 text-sm text-danger" role="alert">
              {t(errors.case_number, errors.case_number)}
            </p>
          )}
        </div>

        {/* Email */}
        <div>
          <label
            htmlFor="email"
            className="mb-1.5 block text-sm font-medium text-neutral-700"
          >
            {t('magic_link.email', 'E-Mail-Adresse')}
            <span className="ml-1 text-danger" aria-hidden="true">*</span>
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setErrors((prev) => {
                if (!prev.email) return prev;
                const next = { ...prev };
                delete next.email;
                return next;
              });
            }}
            autoComplete="email"
            aria-required="true"
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? 'email-error' : 'email-hint'}
            className={inputClasses('email')}
            placeholder="ihre.email@beispiel.de"
          />
          <p id="email-hint" className="mt-1 text-xs text-neutral-500">
            {t(
              'magic_link.email_hint',
              'Die E-Mail-Adresse, die Sie bei der Meldung angegeben haben.',
            )}
          </p>
          {errors.email && (
            <p id="email-error" className="mt-1.5 text-sm text-danger" role="alert">
              {t(errors.email, errors.email)}
            </p>
          )}
        </div>

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
            ? t('magic_link.sending', 'Link wird gesendet...')
            : t('magic_link.submit', 'Login-Link anfordern')}
        </button>
      </form>

      {/* Back links */}
      <div className="mt-6 border-t border-neutral-200 pt-6 text-center">
        <Link
          to="/mailbox/login"
          className="text-sm font-medium text-primary transition-colors hover:text-primary-dark"
        >
          {t('magic_link.use_passphrase', 'Mit Passphrase anmelden')}
        </Link>
      </div>

      <div className="mt-4 text-center">
        <Link
          to="/"
          className="text-sm text-neutral-500 transition-colors hover:text-neutral-700"
        >
          {t('magic_link.back_home', 'Zur Startseite')}
        </Link>
      </div>
    </div>
  );
}
