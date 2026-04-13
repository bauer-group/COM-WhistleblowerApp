/**
 * Hinweisgebersystem - LanguageSelector Component.
 *
 * DE/EN language dropdown for the reporter frontend.
 * Changes the i18n language instance on selection.
 * No localStorage is used in anonymous mode — language detection
 * relies on the browser's navigator language.
 *
 * WCAG 2.1 AA compliant:
 * - Native <select> for full keyboard and screen reader support
 * - aria-label for screen readers
 * - Visible label with globe icon
 * - 4.5:1 contrast ratio
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';

// ── Types ──────────────────────────────────────────────────────

interface LanguageOption {
  code: string;
  label: string;
  /** Short label shown in compact mode. */
  short: string;
}

interface LanguageSelectorProps {
  /** Whether to show the compact (short code) or full label. */
  compact?: boolean;
}

// ── Language options ──────────────────────────────────────────

const LANGUAGES: LanguageOption[] = [
  { code: 'de', label: 'Deutsch', short: 'DE' },
  { code: 'en', label: 'English', short: 'EN' },
];

// ── Component ─────────────────────────────────────────────────

export default function LanguageSelector({
  compact = false,
}: LanguageSelectorProps) {
  const { i18n, t } = useTranslation('common');

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newLang = e.target.value;
      i18n.changeLanguage(newLang);
    },
    [i18n],
  );

  // Normalize the current language (e.g. "de-DE" → "de")
  const currentLang = i18n.language?.split('-')[0] ?? 'de';

  return (
    <div className="inline-flex items-center gap-1.5">
      {/* Globe icon */}
      <svg
        className="h-4 w-4 text-neutral-500"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M12 21a9 9 0 100-18 9 9 0 000 18zM3.6 9h16.8M3.6 15h16.8M12 3a15.3 15.3 0 014 9 15.3 15.3 0 01-4 9 15.3 15.3 0 01-4-9 15.3 15.3 0 014-9z"
        />
      </svg>

      <select
        value={currentLang}
        onChange={handleChange}
        aria-label={t('language.selector_label', 'Sprache auswählen')}
        className="cursor-pointer rounded border-none bg-transparent py-0.5 pr-6 pl-0 text-sm text-neutral-700 transition-colors hover:text-primary focus:ring-2 focus:ring-primary focus:ring-offset-1"
      >
        {LANGUAGES.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {compact ? lang.short : lang.label}
          </option>
        ))}
      </select>
    </div>
  );
}
