/**
 * Hinweisgebersystem – TwoFactorChallenge Component.
 *
 * Shown after OIDC login when the user has TOTP 2FA enabled.
 * Presents a 6-digit code input (from an authenticator app) or
 * allows the user to enter a single-use backup code instead.
 *
 * The OIDC callback provides a short-lived challenge token (5 min)
 * which is submitted alongside the TOTP code to complete the
 * two-factor authentication and obtain the full session JWT.
 *
 * Designed to be shown as a full-page interstitial by the AuthGuard
 * or the OIDC callback page.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useCallback, useState } from 'react';
import { completeTOTPChallenge } from '@/api/auth';

// ── Types ─────────────────────────────────────────────────────

interface TwoFactorChallengeProps {
  /** The challenge token received from the OIDC callback. */
  challengeToken: string;
  /** Callback fired after successful 2FA verification. */
  onSuccess: () => void;
  /** Callback fired when the user wants to cancel/logout. */
  onCancel?: () => void;
}

// ── Component ────────────────────────────────────────────────

/**
 * TOTP 2FA challenge modal/page.
 *
 * Accepts a 6-digit TOTP code or a backup code, submits it
 * with the challenge token, and calls `onSuccess` on completion.
 */
export default function TwoFactorChallenge({
  challengeToken,
  onSuccess,
  onCancel,
}: TwoFactorChallengeProps) {
  // ── State ──────────────────────────────────────────────────
  const [code, setCode] = useState('');
  const [useBackupCode, setUseBackupCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // ── Handlers ──────────────────────────────────────────────

  /** Submit the TOTP / backup code to complete the 2FA challenge. */
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      const trimmedCode = code.trim();

      if (!useBackupCode && !/^\d{6}$/.test(trimmedCode)) {
        setError('Bitte geben Sie einen 6-stelligen Code ein.');
        return;
      }

      if (useBackupCode && trimmedCode.length === 0) {
        setError('Bitte geben Sie einen Backup-Code ein.');
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        await completeTOTPChallenge({
          challenge_token: challengeToken,
          code: trimmedCode,
        });
        onSuccess();
      } catch (err: unknown) {
        const message =
          err instanceof Error
            ? err.message
            : 'Ungültiger Code. Bitte versuchen Sie es erneut.';
        setError(message);
      } finally {
        setIsLoading(false);
      }
    },
    [code, useBackupCode, challengeToken, onSuccess],
  );

  /** Toggle between TOTP code and backup code input modes. */
  const handleToggleBackupCode = useCallback(() => {
    setUseBackupCode((prev) => !prev);
    setCode('');
    setError(null);
  }, []);

  // ── Render ─────────────────────────────────────────────────

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-neutral-50 px-4"
      role="main"
      aria-label="Zwei-Faktor-Authentifizierung"
    >
      <div className="w-full max-w-md rounded-xl border border-neutral-200 bg-white p-8 shadow-sm">
        {/* Header */}
        <div className="mb-6 text-center">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10"
            aria-hidden="true"
          >
            <svg
              className="h-6 w-6 text-primary"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
              />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-neutral-900">
            Zwei-Faktor-Authentifizierung
          </h1>
          <p className="mt-2 text-sm text-neutral-600">
            {useBackupCode
              ? 'Geben Sie einen Ihrer Backup-Codes ein.'
              : 'Geben Sie den 6-stelligen Code aus Ihrer Authenticator-App ein.'}
          </p>
        </div>

        {/* Error */}
        {error && (
          <div
            className="mb-4 rounded-lg border border-danger/20 bg-danger/5 p-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="totp-challenge-code"
              className="mb-1 block text-sm font-medium text-neutral-700"
            >
              {useBackupCode ? 'Backup-Code' : 'Bestätigungscode'}
            </label>
            {useBackupCode ? (
              <input
                id="totp-challenge-code"
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="xxxx-xxxx-xxxx"
                autoComplete="off"
                autoFocus
                className="w-full rounded-lg border border-neutral-300 px-4 py-3 text-center font-mono text-lg tracking-wider focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
                aria-describedby="totp-challenge-hint"
              />
            ) : (
              <input
                id="totp-challenge-code"
                type="text"
                inputMode="numeric"
                pattern="\d{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                autoComplete="one-time-code"
                autoFocus
                className="w-full rounded-lg border border-neutral-300 px-4 py-3 text-center font-mono text-2xl tracking-widest focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
                aria-describedby="totp-challenge-hint"
              />
            )}
            <p id="totp-challenge-hint" className="mt-1 text-xs text-neutral-500">
              {useBackupCode
                ? 'Einmaliger Backup-Code aus Ihrer gespeicherten Liste'
                : '6-stelliger Code aus Ihrer Authenticator-App'}
            </p>
          </div>

          <button
            type="submit"
            disabled={isLoading || code.trim().length === 0}
            className="w-full rounded-lg bg-primary px-4 py-3 text-sm font-medium text-white hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
          >
            {isLoading ? 'Wird überprüft…' : 'Anmelden'}
          </button>
        </form>

        {/* Toggle backup code / TOTP mode */}
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={handleToggleBackupCode}
            className="text-sm text-primary hover:text-primary/80 hover:underline focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2"
          >
            {useBackupCode
              ? 'Authenticator-Code verwenden'
              : 'Backup-Code verwenden'}
          </button>
        </div>

        {/* Cancel / Logout */}
        {onCancel && (
          <div className="mt-3 text-center">
            <button
              type="button"
              onClick={onCancel}
              className="text-sm text-neutral-500 hover:text-neutral-700 hover:underline focus:outline-none"
            >
              Abmelden
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
