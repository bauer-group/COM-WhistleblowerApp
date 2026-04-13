/**
 * Hinweisgebersystem – Internal Note Editor Component.
 *
 * Rich-text internal note editor for handler-to-handler communication.
 * Internal notes are never visible to the reporter in the anonymous
 * mailbox — they are strictly for investigation documentation and
 * team coordination.
 *
 * Features:
 * - Textarea with auto-resize behavior
 * - Character count with configurable maximum
 * - Clear visual indicator that notes are internal-only
 * - Submit with keyboard shortcut (Ctrl+Enter)
 * - Loading state during submission
 * - ARIA labels for accessibility
 */

import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

// ── Types ─────────────────────────────────────────────────────

interface InternalNoteProps {
  /** Callback when the note is submitted. */
  onSubmit: (content: string) => void;
  /** Whether a submission is currently in progress. */
  isSubmitting?: boolean;
  /** Maximum character count. Defaults to 5000. */
  maxLength?: number;
  /** Placeholder text for the textarea. */
  placeholder?: string;
}

// ── Constants ────────────────────────────────────────────────

const DEFAULT_MAX_LENGTH = 5000;

// ── Component ────────────────────────────────────────────────

/**
 * Internal note editor with submit button and visual "internal only" indicator.
 *
 * Notes created through this component are marked as ``is_internal: true``
 * at the API level and are excluded from the reporter's mailbox view.
 */
export default function InternalNote({
  onSubmit,
  isSubmitting = false,
  maxLength = DEFAULT_MAX_LENGTH,
  placeholder,
}: InternalNoteProps) {
  const [content, setContent] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { t } = useTranslation('cases');

  const resolvedPlaceholder = placeholder ?? t('detail.notes.default_placeholder', 'Interne Notiz verfassen… (nur für Sachbearbeiter sichtbar)');

  const trimmedContent = content.trim();
  const charCount = trimmedContent.length;
  const isOverLimit = charCount > maxLength;
  const canSubmit = charCount > 0 && !isOverLimit && !isSubmitting;

  // ── Auto-resize ────────────────────────────────────────────

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value);

    // Auto-resize textarea to fit content
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 300)}px`;
  }, []);

  // ── Submit ─────────────────────────────────────────────────

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;

    onSubmit(trimmedContent);
    setContent('');

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [canSubmit, trimmedContent, onSubmit]);

  // ── Keyboard Shortcut ──────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  // ── Character Count Color ──────────────────────────────────

  const charCountColor = isOverLimit
    ? 'text-danger'
    : charCount > maxLength * 0.9
      ? 'text-warning'
      : 'text-neutral-400';

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4">
      {/* Internal-only indicator */}
      <div className="mb-3 flex items-center gap-2">
        <svg
          className="h-4 w-4 text-amber-600"
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
        <span className="text-xs font-semibold uppercase tracking-wider text-amber-700">
          {t('detail.notes.title', 'Interne Notiz')}
        </span>
        <span className="text-xs text-amber-600">
          {t('detail.notes.not_visible', '— Nicht sichtbar für den Hinweisgeber')}
        </span>
      </div>

      {/* Textarea */}
      <div className="relative">
        <label htmlFor="internal-note-input" className="sr-only">
          {t('detail.notes.compose_label', 'Interne Notiz verfassen')}
        </label>
        <textarea
          ref={textareaRef}
          id="internal-note-input"
          value={content}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={resolvedPlaceholder}
          rows={3}
          disabled={isSubmitting}
          aria-describedby="note-char-count note-keyboard-hint"
          className="w-full resize-none rounded-md border border-amber-300 bg-white px-3 py-2 text-sm text-neutral-900 transition-colors placeholder:text-neutral-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {/* Footer: character count + submit button */}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            id="note-char-count"
            className={`text-xs ${charCountColor}`}
            aria-live="polite"
          >
            {charCount} / {maxLength}
          </span>
          <span
            id="note-keyboard-hint"
            className="hidden text-xs text-neutral-400 sm:inline"
          >
            {t('detail.notes.keyboard_hint', 'Ctrl+Enter zum Absenden')}
          </span>
        </div>

        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={t('detail.notes.save_aria', 'Interne Notiz speichern')}
        >
          {isSubmitting ? (
            <>
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
              {t('detail.notes.saving', 'Wird gespeichert…')}
            </>
          ) : (
            <>
              <svg
                className="h-3.5 w-3.5"
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
              {t('detail.notes.send', 'Notiz speichern')}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
