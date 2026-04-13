/**
 * Hinweisgebersystem – Custodian Identity Disclosure Dialog.
 *
 * Implements the 4-eyes identity disclosure workflow as a modal dialog:
 *
 * 1. **Request Step** (Handler): The handler submits a disclosure request
 *    with a mandatory reason explaining why identity access is needed.
 *
 * 2. **Approval Step** (Custodian): A designated custodian (different
 *    person from the requester) reviews the request and approves or
 *    rejects it with an optional decision reason.
 *
 * 3. **Result Step**: If approved, the requester can reveal the sealed
 *    reporter identity. The revealed data is displayed once and logged
 *    for compliance.
 *
 * The dialog enforces the 4-eyes principle: the custodian must be a
 * different person than the handler who requested the disclosure.
 *
 * All actions are audit-logged for HinSchG/LkSG compliance.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  DisclosureResponse,
  DisclosureStatus,
  IdentityRevealResponse,
} from '@/api/cases';

// ── Types ─────────────────────────────────────────────────────

interface CustodianDialogProps {
  /** Whether the dialog is open. */
  isOpen: boolean;
  /** Callback to close the dialog. */
  onClose: () => void;
  /** The report ID for which identity disclosure is requested. */
  reportId: string;
  /** Whether the case is anonymous (non-anonymous cases don't need disclosure). */
  isAnonymous: boolean;
  /** Existing disclosure requests for this report. */
  existingDisclosures: DisclosureResponse[];
  /** Whether the current user is a custodian. */
  isCustodian: boolean;
  /** Callback to request identity disclosure. */
  onRequestDisclosure: (reason: string) => void;
  /** Callback to approve or reject a disclosure request. */
  onDecideDisclosure: (
    disclosureId: string,
    approved: boolean,
    decisionReason?: string,
  ) => void;
  /** Callback to reveal the identity after approval. */
  onRevealIdentity: (disclosureId: string) => void;
  /** Revealed identity data (null until revealed). */
  revealedIdentity: IdentityRevealResponse | null;
  /** Whether a request is being submitted. */
  isRequesting?: boolean;
  /** Whether a decision is being submitted. */
  isDeciding?: boolean;
  /** Whether identity reveal is in progress. */
  isRevealing?: boolean;
}

// ── Disclosure Status Helpers ────────────────────────────────

const DISCLOSURE_STATUS_STYLES: Record<DisclosureStatus, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  expired: 'bg-neutral-100 text-neutral-600',
};

// ── Request Form ─────────────────────────────────────────────

interface RequestFormProps {
  onSubmit: (reason: string) => void;
  isSubmitting: boolean;
}

function RequestForm({ onSubmit, isSubmitting }: RequestFormProps) {
  const { t } = useTranslation('cases');
  const [reason, setReason] = useState('');
  const trimmedReason = reason.trim();
  const canSubmit = trimmedReason.length >= 10 && !isSubmitting;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSubmit) return;
      onSubmit(trimmedReason);
    },
    [canSubmit, trimmedReason, onSubmit],
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label
          htmlFor="disclosure-reason"
          className="mb-1 block text-sm font-medium text-neutral-700"
        >
          {t('disclosure.request.reason_label', 'Begründung der Identitätsoffenlegung *')}
        </label>
        <p className="mb-2 text-xs text-neutral-500">
          {t('disclosure.request.reason_hint', 'Erläutern Sie, warum der Zugriff auf die Identität des Hinweisgebers für die Bearbeitung dieses Falls erforderlich ist. Diese Begründung wird im Audit-Protokoll dokumentiert.')}
        </p>
        <textarea
          id="disclosure-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t('disclosure.request.reason_placeholder', 'Begründung eingeben (mindestens 10 Zeichen)…')}
          rows={4}
          required
          minLength={10}
          disabled={isSubmitting}
          className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
          aria-describedby="reason-hint"
        />
        <p id="reason-hint" className="mt-1 text-xs text-neutral-400">
          {trimmedReason.length}{' / '}{t('disclosure.request.min_chars', 'mindestens 10 Zeichen')}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-danger/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              {t('disclosure.request.submitting', 'Wird angefragt…')}
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
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
              {t('disclosure.request.submit', 'Offenlegung anfragen')}
            </>
          )}
        </button>
      </div>
    </form>
  );
}

// ── Approval Form ────────────────────────────────────────────

interface ApprovalFormProps {
  disclosure: DisclosureResponse;
  onDecide: (approved: boolean, reason?: string) => void;
  isDeciding: boolean;
}

function ApprovalForm({ disclosure, onDecide, isDeciding }: ApprovalFormProps) {
  const { t } = useTranslation('cases');
  const [decisionReason, setDecisionReason] = useState('');

  const handleApprove = useCallback(() => {
    onDecide(true, decisionReason.trim() || undefined);
  }, [decisionReason, onDecide]);

  const handleReject = useCallback(() => {
    onDecide(false, decisionReason.trim() || undefined);
  }, [decisionReason, onDecide]);

  return (
    <div className="space-y-4">
      {/* Request Details */}
      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4">
        <h4 className="mb-2 text-sm font-semibold text-neutral-700">
          {t('disclosure.approval.details', 'Anfrage-Details')}
        </h4>
        <dl className="space-y-2 text-sm">
          <div>
            <dt className="text-xs font-medium text-neutral-500">{t('disclosure.approval.reason', 'Begründung')}</dt>
            <dd className="mt-0.5 text-neutral-900">{disclosure.reason}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-neutral-500">
              {t('disclosure.approval.requested_at', 'Angefragt am')}
            </dt>
            <dd className="mt-0.5 text-neutral-900">
              {new Date(disclosure.created_at).toLocaleString('de-DE', {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </dd>
          </div>
        </dl>
      </div>

      {/* Decision Reason */}
      <div>
        <label
          htmlFor="decision-reason"
          className="mb-1 block text-sm font-medium text-neutral-700"
        >
          {t('disclosure.approval.decision_reason_label', 'Entscheidungsbegründung (optional)')}
        </label>
        <textarea
          id="decision-reason"
          value={decisionReason}
          onChange={(e) => setDecisionReason(e.target.value)}
          placeholder={t('disclosure.approval.decision_reason_placeholder', 'Optionale Begründung für Ihre Entscheidung…')}
          rows={3}
          disabled={isDeciding}
          className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {/* Decision Buttons */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleApprove}
          disabled={isDeciding}
          className="inline-flex items-center gap-1.5 rounded-md bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDeciding ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
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
                d="M5 13l4 4L19 7"
              />
            </svg>
          )}
          {t('disclosure.approval.approve', 'Genehmigen')}
        </button>

        <button
          type="button"
          onClick={handleReject}
          disabled={isDeciding}
          className="inline-flex items-center gap-1.5 rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-danger/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDeciding ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
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
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          )}
          {t('disclosure.approval.reject', 'Ablehnen')}
        </button>
      </div>
    </div>
  );
}

// ── Identity Reveal Display ──────────────────────────────────

interface IdentityRevealProps {
  identity: IdentityRevealResponse;
}

function IdentityReveal({ identity }: IdentityRevealProps) {
  const { t } = useTranslation('cases');
  return (
    <div
      className="rounded-lg border-2 border-danger/30 bg-danger/5 p-4"
      role="alert"
    >
      <div className="mb-3 flex items-center gap-2">
        <svg
          className="h-5 w-5 text-danger"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
          />
        </svg>
        <h4 className="text-sm font-semibold text-danger">
          {t('disclosure.reveal.title', 'Offengelegte Identität')}
        </h4>
      </div>

      <p className="mb-3 text-xs text-neutral-600">
        {t('disclosure.reveal.note', 'Diese Informationen wurden im Rahmen des Vier-Augen-Prinzips offengelegt. Der Zugriff wurde protokolliert.')}
      </p>

      <dl className="space-y-2">
        <div className="flex items-center gap-3">
          <dt className="w-20 text-xs font-medium text-neutral-500">{t('disclosure.reveal.name', 'Name')}</dt>
          <dd className="text-sm font-medium text-neutral-900">
            {identity.reporter_name ?? '–'}
          </dd>
        </div>
        <div className="flex items-center gap-3">
          <dt className="w-20 text-xs font-medium text-neutral-500">{t('disclosure.reveal.email', 'E-Mail')}</dt>
          <dd className="text-sm font-medium text-neutral-900">
            {identity.reporter_email ?? '–'}
          </dd>
        </div>
        <div className="flex items-center gap-3">
          <dt className="w-20 text-xs font-medium text-neutral-500">{t('disclosure.reveal.phone', 'Telefon')}</dt>
          <dd className="text-sm font-medium text-neutral-900">
            {identity.reporter_phone ?? '–'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

// ── Reveal Button ────────────────────────────────────────────

interface RevealButtonProps {
  disclosureId: string;
  onReveal: (disclosureId: string) => void;
  isRevealing: boolean;
}

function RevealButton({ disclosureId, onReveal, isRevealing }: RevealButtonProps) {
  const { t } = useTranslation('cases');
  const [confirmed, setConfirmed] = useState(false);

  const handleClick = useCallback(() => {
    if (!confirmed) {
      setConfirmed(true);
      return;
    }
    onReveal(disclosureId);
  }, [confirmed, disclosureId, onReveal]);

  return (
    <div className="space-y-2">
      {confirmed && (
        <p className="text-xs font-medium text-danger">
          {t('disclosure.reveal.confirm_warning', 'Sind Sie sicher? Der Zugriff wird protokolliert und ist nicht rückgängig zu machen.')}
        </p>
      )}
      <button
        type="button"
        onClick={handleClick}
        disabled={isRevealing}
        className="inline-flex items-center gap-1.5 rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-danger/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isRevealing ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            {t('disclosure.reveal.revealing', 'Wird offengelegt…')}
          </>
        ) : confirmed ? (
          t('disclosure.reveal.reveal_now', 'Identität jetzt offenlegen')
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
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
              />
            </svg>
            {t('disclosure.reveal.reveal_button', 'Identität offenlegen')}
          </>
        )}
      </button>
    </div>
  );
}

// ── Disclosure History ───────────────────────────────────────

interface DisclosureHistoryProps {
  disclosures: DisclosureResponse[];
  isCustodian: boolean;
  onDecide: (
    disclosureId: string,
    approved: boolean,
    reason?: string,
  ) => void;
  onReveal: (disclosureId: string) => void;
  revealedIdentity: IdentityRevealResponse | null;
  isDeciding: boolean;
  isRevealing: boolean;
}

function DisclosureHistory({
  disclosures,
  isCustodian,
  onDecide,
  onReveal,
  revealedIdentity,
  isDeciding,
  isRevealing,
}: DisclosureHistoryProps) {
  const { t } = useTranslation('cases');
  if (disclosures.length === 0) return null;

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-neutral-700">
        {t('disclosure.history', 'Bisherige Anfragen')}
      </h4>

      {disclosures.map((disclosure) => (
        <div
          key={disclosure.id}
          className="rounded-lg border border-neutral-200 bg-white p-4"
        >
          {/* Header */}
          <div className="mb-2 flex items-center justify-between">
            <span
              className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${DISCLOSURE_STATUS_STYLES[disclosure.status]}`}
            >
              {t('disclosure.status.' + disclosure.status, disclosure.status)}
            </span>
            <time
              className="text-xs text-neutral-400"
              dateTime={disclosure.created_at}
            >
              {new Date(disclosure.created_at).toLocaleString('de-DE', {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </time>
          </div>

          {/* Reason */}
          <p className="mb-2 text-sm text-neutral-700">{disclosure.reason}</p>

          {/* Decision reason if present */}
          {disclosure.decision_reason && (
            <p className="mb-2 text-xs text-neutral-500">
              <span className="font-medium">{t('disclosure.approval.decision_label', 'Entscheidung:')}</span>{' '}
              {disclosure.decision_reason}
            </p>
          )}

          {/* Custodian approval form for pending requests */}
          {disclosure.status === 'pending' && isCustodian && (
            <div className="mt-3 border-t border-neutral-200 pt-3">
              <ApprovalForm
                disclosure={disclosure}
                onDecide={(approved, reason) =>
                  onDecide(disclosure.id, approved, reason)
                }
                isDeciding={isDeciding}
              />
            </div>
          )}

          {/* Reveal button for approved disclosures */}
          {disclosure.status === 'approved' && !revealedIdentity && (
            <div className="mt-3 border-t border-neutral-200 pt-3">
              <RevealButton
                disclosureId={disclosure.id}
                onReveal={onReveal}
                isRevealing={isRevealing}
              />
            </div>
          )}

          {/* Revealed identity */}
          {disclosure.status === 'approved' &&
            revealedIdentity?.disclosure_id === disclosure.id && (
              <div className="mt-3 border-t border-neutral-200 pt-3">
                <IdentityReveal identity={revealedIdentity} />
              </div>
            )}
        </div>
      ))}
    </div>
  );
}

// ── CustodianDialog Component ────────────────────────────────

/**
 * Modal dialog for the 4-eyes identity disclosure workflow.
 *
 * Supports three workflow phases:
 * 1. Request phase: Handler submits a disclosure request with reason
 * 2. Approval phase: Custodian approves or rejects
 * 3. Reveal phase: Approved requester can view the sealed identity
 *
 * If the report is not anonymous, shows an informational message
 * instead of the disclosure workflow.
 */
export default function CustodianDialog({
  isOpen,
  onClose,
  reportId,
  isAnonymous,
  existingDisclosures,
  isCustodian,
  onRequestDisclosure,
  onDecideDisclosure,
  onRevealIdentity,
  revealedIdentity,
  isRequesting = false,
  isDeciding = false,
  isRevealing = false,
}: CustodianDialogProps) {
  const { t } = useTranslation('cases');
  const dialogRef = useRef<HTMLDivElement>(null);

  // ── Escape key handler and focus trap ──────────────────────
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }

      // Focus trap: cycle through focusable elements
      if (e.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    // Focus the dialog on open
    const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    firstFocusable?.focus();

    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const hasPendingRequest = existingDisclosures.some(
    (d) => d.status === 'pending',
  );

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        ref={dialogRef}
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="custodian-dialog-title"
      >
        <div className="w-full max-w-lg rounded-xl border border-neutral-200 bg-white shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
            <div className="flex items-center gap-2">
              <svg
                className="h-5 w-5 text-danger"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                />
              </svg>
              <h2
                id="custodian-dialog-title"
                className="text-lg font-semibold text-neutral-900"
              >
                {t('disclosure.title', 'Identitätsoffenlegung')}
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              aria-label={t('common:aria.close_dialog', 'Dialog schließen')}
            >
              <svg
                className="h-5 w-5"
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
            </button>
          </div>

          {/* Content */}
          <div className="max-h-[70vh] overflow-y-auto px-6 py-4">
            {!isAnonymous ? (
              /* Non-anonymous case — identity already available */
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
                <p className="font-medium">
                  {t('disclosure.not_anonymous.title', 'Dieser Fall ist nicht anonym.')}
                </p>
                <p className="mt-1 text-blue-600">
                  {t('disclosure.not_anonymous.message', 'Die Identitätsdaten des Hinweisgebers sind in den Falldetails direkt einsehbar. Eine gesonderte Offenlegungsanfrage ist nicht erforderlich.')}
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* 4-eyes principle explanation */}
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  <p className="font-medium">{t('disclosure.four_eyes.title', 'Vier-Augen-Prinzip')}</p>
                  <p className="mt-1 text-amber-600">
                    {t('disclosure.four_eyes.description', 'Die Offenlegung der Hinweisgeber-Identität erfordert die Genehmigung durch einen Vertrauensperson (Custodian). Alle Zugriffe werden im Audit-Protokoll dokumentiert.')}
                  </p>
                </div>

                {/* Existing disclosures */}
                <DisclosureHistory
                  disclosures={existingDisclosures}
                  isCustodian={isCustodian}
                  onDecide={onDecideDisclosure}
                  onReveal={onRevealIdentity}
                  revealedIdentity={revealedIdentity}
                  isDeciding={isDeciding}
                  isRevealing={isRevealing}
                />

                {/* New request form (only if no pending request) */}
                {!hasPendingRequest && !revealedIdentity && (
                  <div>
                    <h4 className="mb-3 text-sm font-semibold text-neutral-700">
                      {t('disclosure.new_request', 'Neue Offenlegungsanfrage')}
                    </h4>
                    <RequestForm
                      onSubmit={onRequestDisclosure}
                      isSubmitting={isRequesting}
                    />
                  </div>
                )}

                {hasPendingRequest && !isCustodian && (
                  <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
                    <p className="font-medium">{t('disclosure.pending.title', 'Anfrage ausstehend')}</p>
                    <p className="mt-1 text-yellow-600">
                      {t('disclosure.pending.message', 'Ihre Offenlegungsanfrage wartet auf die Genehmigung durch die Vertrauensperson.')}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-end border-t border-neutral-200 px-6 py-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-50"
            >
              {t('common:buttons.close', 'Schließen')}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
