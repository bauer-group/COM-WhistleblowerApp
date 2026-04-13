/**
 * Hinweisgebersystem – TwoFactorSetup Component.
 *
 * Guided setup flow for TOTP two-factor authentication.
 * Walks the user through three stages:
 *
 *  1. **QR Code** – Scan with an authenticator app (Google Authenticator,
 *     Authy, etc.) or manually enter the Base32 secret.
 *  2. **Backup Codes** – Display 10 single-use recovery codes that the
 *     user must save before continuing.
 *  3. **Verification** – Enter a 6-digit TOTP code to confirm the
 *     authenticator is configured correctly and activate 2FA.
 *
 * Designed to be embedded in the Settings page as a dedicated section.
 * Uses the auth API client for all server communication.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { QRCodeSVG } from 'qrcode.react';
import type { TOTPSetupResponse } from '@/api/auth';
import { setupTOTP, verifyTOTP, disableTOTP } from '@/api/auth';

// ── Types ─────────────────────────────────────────────────────

interface TwoFactorSetupProps {
  /** Whether 2FA is currently enabled on the user's account. */
  isEnabled?: boolean;
  /** Callback fired after 2FA is successfully enabled or disabled. */
  onStatusChange?: (enabled: boolean) => void;
}

type SetupStage = 'idle' | 'qr_code' | 'backup_codes' | 'verify' | 'disable';

// ── Component ────────────────────────────────────────────────

/**
 * TOTP 2FA setup and management UI.
 *
 * When 2FA is not yet enabled, shows a button to begin setup.
 * When 2FA is already enabled, shows status and a disable option.
 */
export default function TwoFactorSetup({
  isEnabled = false,
  onStatusChange,
}: TwoFactorSetupProps) {
  const { t } = useTranslation('admin');

  // ── State ──────────────────────────────────────────────────
  const [stage, setStage] = useState<SetupStage>('idle');
  const [setupData, setSetupData] = useState<TOTPSetupResponse | null>(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [backupCodesCopied, setBackupCodesCopied] = useState(false);

  // ── Handlers ──────────────────────────────────────────────

  /** Initiate TOTP setup — fetches secret, provisioning URI, and backup codes. */
  const handleBeginSetup = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await setupTOTP();
      setSetupData(data);
      setStage('qr_code');
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Fehler beim Einrichten der 2FA.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /** Advance from QR code stage to backup codes. */
  const handleProceedToBackupCodes = useCallback(() => {
    setStage('backup_codes');
  }, []);

  /** Advance from backup codes to verification. */
  const handleProceedToVerify = useCallback(() => {
    if (!backupCodesCopied) return;
    setStage('verify');
  }, [backupCodesCopied]);

  /** Copy backup codes to clipboard. */
  const handleCopyBackupCodes = useCallback(async () => {
    if (!setupData) return;

    try {
      await navigator.clipboard.writeText(setupData.backup_codes.join('\n'));
      setBackupCodesCopied(true);
    } catch {
      // Fallback: mark as copied anyway (user can still read them on screen)
      setBackupCodesCopied(true);
    }
  }, [setupData]);

  /** Verify the TOTP code and activate 2FA. */
  const handleVerify = useCallback(async () => {
    if (!/^\d{6}$/.test(verifyCode)) {
      setError('Bitte geben Sie einen 6-stelligen Code ein.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await verifyTOTP({ code: verifyCode });
      setStage('idle');
      setSetupData(null);
      setVerifyCode('');
      onStatusChange?.(true);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Ungültiger Bestätigungscode.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [verifyCode, onStatusChange]);

  /** Disable 2FA with a confirmation code. */
  const handleDisable = useCallback(async () => {
    if (!/^\d{6}$/.test(disableCode)) {
      setError('Bitte geben Sie einen 6-stelligen Code ein.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await disableTOTP({ code: disableCode });
      setStage('idle');
      setDisableCode('');
      onStatusChange?.(false);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Fehler beim Deaktivieren der 2FA.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [disableCode, onStatusChange]);

  /** Cancel any in-progress operation. */
  const handleCancel = useCallback(() => {
    setStage('idle');
    setSetupData(null);
    setVerifyCode('');
    setDisableCode('');
    setError(null);
    setBackupCodesCopied(false);
  }, []);

  // ── Render Helpers ────────────────────────────────────────

  /** Error alert banner. */
  const renderError = () => {
    if (!error) return null;

    return (
      <div
        className="mb-4 rounded-lg border border-danger/20 bg-danger/5 p-3 text-sm text-danger"
        role="alert"
      >
        {error}
      </div>
    );
  };

  /** Idle state — show current 2FA status and action buttons. */
  const renderIdle = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div
          className={`h-3 w-3 rounded-full ${isEnabled ? 'bg-success' : 'bg-neutral-300'}`}
          aria-hidden="true"
        />
        <span className="text-sm font-medium text-neutral-700">
          {isEnabled
            ? 'Zwei-Faktor-Authentifizierung ist aktiviert'
            : 'Zwei-Faktor-Authentifizierung ist nicht aktiviert'}
        </span>
      </div>

      {isEnabled ? (
        <button
          type="button"
          onClick={() => setStage('disable')}
          className="rounded-lg border border-danger/30 px-4 py-2 text-sm font-medium text-danger hover:bg-danger/5 focus:outline-none focus:ring-2 focus:ring-danger/50"
        >
          2FA deaktivieren
        </button>
      ) : (
        <button
          type="button"
          onClick={handleBeginSetup}
          disabled={isLoading}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
        >
          {isLoading ? 'Wird eingerichtet…' : '2FA einrichten'}
        </button>
      )}
    </div>
  );

  /** Stage 1: QR Code display. */
  const renderQRCode = () => {
    if (!setupData) return null;

    return (
      <div className="space-y-4">
        <h3 className="text-base font-semibold text-neutral-900">
          Schritt 1: Authenticator-App einrichten
        </h3>
        <p className="text-sm text-neutral-600">
          Scannen Sie den QR-Code mit Ihrer Authenticator-App (z.B. Google
          Authenticator, Authy, Microsoft Authenticator).
        </p>

        {/* QR Code Display Area */}
        <div
          className="flex items-center justify-center rounded-lg border-2 border-dashed border-neutral-300 bg-neutral-50 p-8"
          aria-label="QR-Code für Authenticator-App"
        >
          <div className="text-center">
            {/* QR code generated entirely client-side — no network requests */}
            <QRCodeSVG
              value={setupData.provisioning_uri}
              size={200}
              level="M"
              className="mx-auto"
              role="img"
              aria-label="TOTP QR-Code"
            />
          </div>
        </div>

        {/* Manual secret entry fallback */}
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-neutral-700 hover:text-neutral-900">
            QR-Code kann nicht gescannt werden? Manuell eingeben
          </summary>
          <div className="mt-2 rounded-lg bg-neutral-100 p-3">
            <p className="mb-1 text-xs text-neutral-500">Geheimschlüssel:</p>
            <code className="select-all break-all text-sm font-mono text-neutral-900">
              {setupData.secret}
            </code>
          </div>
        </details>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-300"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={handleProceedToBackupCodes}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            Weiter
          </button>
        </div>
      </div>
    );
  };

  /** Stage 2: Backup codes display. */
  const renderBackupCodes = () => {
    if (!setupData) return null;

    return (
      <div className="space-y-4">
        <h3 className="text-base font-semibold text-neutral-900">
          Schritt 2: Backup-Codes sichern
        </h3>
        <p className="text-sm text-neutral-600">
          Speichern Sie diese Backup-Codes an einem sicheren Ort. Jeder Code
          kann nur einmal verwendet werden, falls Sie keinen Zugriff auf Ihre
          Authenticator-App haben.
        </p>

        {/* Backup codes grid */}
        <div
          className="rounded-lg border border-warning/30 bg-warning/5 p-4"
          role="region"
          aria-label="Backup-Codes"
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {setupData.backup_codes.map((code, index) => (
              <div
                key={index}
                className="rounded bg-white px-3 py-2 text-center font-mono text-sm text-neutral-900 shadow-sm"
              >
                {code}
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCopyBackupCodes}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-300"
          >
            {backupCodesCopied ? '✓ Kopiert' : 'Codes kopieren'}
          </button>
          {backupCodesCopied && (
            <span className="text-xs text-success">
              Codes wurden in die Zwischenablage kopiert.
            </span>
          )}
        </div>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-300"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={handleProceedToVerify}
            disabled={!backupCodesCopied}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
          >
            Weiter
          </button>
        </div>
      </div>
    );
  };

  /** Stage 3: Verification input. */
  const renderVerify = () => (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-neutral-900">
        Schritt 3: Code bestätigen
      </h3>
      <p className="text-sm text-neutral-600">
        Geben Sie den 6-stelligen Code aus Ihrer Authenticator-App ein, um die
        Einrichtung abzuschließen.
      </p>

      <div className="max-w-xs">
        <label
          htmlFor="totp-verify-code"
          className="mb-1 block text-sm font-medium text-neutral-700"
        >
          Bestätigungscode
        </label>
        <input
          id="totp-verify-code"
          type="text"
          inputMode="numeric"
          pattern="\d{6}"
          maxLength={6}
          autoComplete="one-time-code"
          value={verifyCode}
          onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ''))}
          placeholder="000000"
          className="w-full rounded-lg border border-neutral-300 px-4 py-2 text-center font-mono text-lg tracking-widest focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
          aria-describedby="totp-verify-hint"
        />
        <p id="totp-verify-hint" className="mt-1 text-xs text-neutral-500">
          6-stelliger Code aus Ihrer Authenticator-App
        </p>
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleCancel}
          className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-300"
        >
          Abbrechen
        </button>
        <button
          type="button"
          onClick={handleVerify}
          disabled={isLoading || verifyCode.length !== 6}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
        >
          {isLoading ? 'Wird überprüft…' : 'Bestätigen & aktivieren'}
        </button>
      </div>
    </div>
  );

  /** Disable 2FA confirmation. */
  const renderDisable = () => (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-neutral-900">
        2FA deaktivieren
      </h3>
      <p className="text-sm text-neutral-600">
        Geben Sie Ihren aktuellen 6-stelligen Code ein, um die
        Zwei-Faktor-Authentifizierung zu deaktivieren.
      </p>

      <div
        className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning"
        role="alert"
      >
        Warnung: Ohne 2FA ist Ihr Konto weniger geschützt.
      </div>

      <div className="max-w-xs">
        <label
          htmlFor="totp-disable-code"
          className="mb-1 block text-sm font-medium text-neutral-700"
        >
          Aktueller Code
        </label>
        <input
          id="totp-disable-code"
          type="text"
          inputMode="numeric"
          pattern="\d{6}"
          maxLength={6}
          autoComplete="one-time-code"
          value={disableCode}
          onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ''))}
          placeholder="000000"
          className="w-full rounded-lg border border-neutral-300 px-4 py-2 text-center font-mono text-lg tracking-widest focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
          aria-describedby="totp-disable-hint"
        />
        <p id="totp-disable-hint" className="mt-1 text-xs text-neutral-500">
          6-stelliger Code aus Ihrer Authenticator-App
        </p>
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleCancel}
          className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 focus:outline-none focus:ring-2 focus:ring-neutral-300"
        >
          Abbrechen
        </button>
        <button
          type="button"
          onClick={handleDisable}
          disabled={isLoading || disableCode.length !== 6}
          className="rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-danger/90 focus:outline-none focus:ring-2 focus:ring-danger/50 disabled:opacity-50"
        >
          {isLoading ? 'Wird deaktiviert…' : '2FA deaktivieren'}
        </button>
      </div>
    </div>
  );

  // ── Main Render ────────────────────────────────────────────

  return (
    <section
      className="space-y-4"
      aria-label="Zwei-Faktor-Authentifizierung"
    >
      <div className="mb-2">
        <h2 className="text-lg font-semibold text-neutral-900">
          Zwei-Faktor-Authentifizierung (2FA)
        </h2>
        <p className="text-sm text-neutral-500">
          Schützen Sie Ihr Konto mit einem zusätzlichen Sicherheitsfaktor über
          eine Authenticator-App (TOTP).
        </p>
      </div>

      {renderError()}

      {stage === 'idle' && renderIdle()}
      {stage === 'qr_code' && renderQRCode()}
      {stage === 'backup_codes' && renderBackupCodes()}
      {stage === 'verify' && renderVerify()}
      {stage === 'disable' && renderDisable()}
    </section>
  );
}
