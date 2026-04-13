/**
 * Hinweisgebersystem - MagicLinkVerify Page Component.
 *
 * Verifies the magic link JWT token from the email URL and
 * redirects to the mailbox on success.  Shows loading state
 * during verification and error state on failure.
 *
 * Expected URL format: /magic-link/verify?token=<jwt>
 *
 * WCAG 2.1 AA compliant:
 * - role="status" for loading state
 * - role="alert" for error messages
 * - Semantic heading hierarchy
 * - Keyboard-accessible action buttons
 * - 4.5:1 contrast ratio
 * - Responsive layout (320px min width)
 */

import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';

import { useVerifyMagicLink } from '@/hooks/useReport';

// ── Types ──────────────────────────────────────────────────────

type VerifyState = 'verifying' | 'success' | 'error' | 'no_token';

// ── Component ─────────────────────────────────────────────────

export default function MagicLinkVerify() {
  const { t } = useTranslation('mailbox');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const verifyMagicLink = useVerifyMagicLink();
  const hasVerified = useRef(false);

  const token = searchParams.get('token');

  const [verifyState, setVerifyState] = useState<VerifyState>(
    token ? 'verifying' : 'no_token',
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // ── Auto-verify on mount ──────────────────────────────────

  useEffect(() => {
    if (!token || hasVerified.current) return;
    hasVerified.current = true;

    verifyMagicLink
      .mutateAsync(token)
      .then((response) => {
        setVerifyState('success');
        // Navigate to mailbox with session data
        navigate('/mailbox', {
          state: {
            token: response.access_token,
            caseNumber: response.case_number,
            channel: response.channel,
            status: response.status,
          },
          replace: true,
        });
      })
      .catch((err: Error) => {
        setVerifyState('error');
        setErrorMessage(
          err.message ||
            t(
              'magic_link_verify.error_generic',
              'Der Link ist ungültig oder abgelaufen.',
            ),
        );
      });
  }, [token, verifyMagicLink, navigate, t]);

  // ── No token provided ─────────────────────────────────────

  if (verifyState === 'no_token') {
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center sm:px-6">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-warning/10">
          <svg
            className="h-7 w-7 text-warning"
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
        </div>
        <h1 className="text-xl font-bold text-neutral-900">
          {t('magic_link_verify.no_token_title', 'Kein Token vorhanden')}
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          {t(
            'magic_link_verify.no_token_text',
            'Bitte öffnen Sie den Link aus Ihrer E-Mail. Diese Seite kann nicht direkt aufgerufen werden.',
          )}
        </p>
        <div className="mt-6 flex flex-col gap-3">
          <Link
            to="/magic-link"
            className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
          >
            {t('magic_link_verify.request_new', 'Neuen Link anfordern')}
          </Link>
          <Link
            to="/"
            className="text-sm text-neutral-500 transition-colors hover:text-neutral-700"
          >
            {t('magic_link_verify.back_home', 'Zur Startseite')}
          </Link>
        </div>
      </div>
    );
  }

  // ── Verifying state ───────────────────────────────────────

  if (verifyState === 'verifying') {
    return (
      <div
        className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center sm:px-6"
        role="status"
        aria-label={t('magic_link_verify.verifying', 'Link wird überprüft...')}
      >
        <div className="mb-4 h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        <h1 className="text-xl font-bold text-neutral-900">
          {t('magic_link_verify.verifying_title', 'Link wird überprüft')}
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          {t(
            'magic_link_verify.verifying_text',
            'Bitte warten Sie, während Ihr Login-Link überprüft wird...',
          )}
        </p>
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────

  if (verifyState === 'error') {
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center sm:px-6">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-danger/10">
          <svg
            className="h-7 w-7 text-danger"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </div>
        <h1 className="text-xl font-bold text-neutral-900">
          {t('magic_link_verify.error_title', 'Link ungültig')}
        </h1>
        <p className="mt-2 text-sm text-neutral-600" role="alert">
          {errorMessage ??
            t(
              'magic_link_verify.error_text',
              'Der Link ist ungültig oder abgelaufen. Bitte fordern Sie einen neuen Link an.',
            )}
        </p>
        <div className="mt-6 flex flex-col gap-3">
          <Link
            to="/magic-link"
            className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark"
          >
            {t('magic_link_verify.request_new', 'Neuen Link anfordern')}
          </Link>
          <Link
            to="/mailbox/login"
            className="inline-flex items-center justify-center rounded-lg border border-neutral-300 bg-white px-4 py-2.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
          >
            {t('magic_link_verify.use_passphrase', 'Mit Passphrase anmelden')}
          </Link>
          <Link
            to="/"
            className="text-sm text-neutral-500 transition-colors hover:text-neutral-700"
          >
            {t('magic_link_verify.back_home', 'Zur Startseite')}
          </Link>
        </div>
      </div>
    );
  }

  // ── Success state (brief flash before redirect) ───────────

  return (
    <div
      className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center sm:px-6"
      role="status"
    >
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
            d="M5 13l4 4L19 7"
          />
        </svg>
      </div>
      <h1 className="text-xl font-bold text-neutral-900">
        {t('magic_link_verify.success_title', 'Erfolgreich verifiziert')}
      </h1>
      <p className="mt-2 text-sm text-neutral-600">
        {t(
          'magic_link_verify.success_text',
          'Sie werden zu Ihrem Postfach weitergeleitet...',
        )}
      </p>
    </div>
  );
}
