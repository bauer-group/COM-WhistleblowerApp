/**
 * Hinweisgebersystem - CategorySelect Component.
 *
 * Category selection for HinSchG and LkSG channels with i18n labels.
 * Categories are loaded from the backend API (per-tenant, per-language)
 * and fall back to static LkSG categories when the API is unavailable.
 *
 * WCAG 2.1 AA compliant:
 * - Native <select> element for full keyboard/screen reader support
 * - Associated <label> with htmlFor
 * - aria-describedby for error messages
 * - 4.5:1 contrast ratio
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import apiClient from '@/api/client';
import type { Channel, LkSGCategory } from '@/schemas/report';

// ── Types ──────────────────────────────────────────────────────

interface CategoryOption {
  value: string;
  label: string;
}

interface CategorySelectProps {
  /** Current channel determines which categories to show. */
  channel: Channel;
  /** Currently selected category value. */
  value: string | null | undefined;
  /** Callback when the selection changes. */
  onChange: (value: string) => void;
  /** Error message to display (e.g. from Zod validation). */
  error?: string;
  /** Whether the field is disabled. */
  disabled?: boolean;
  /** HTML id for the select element (for label association). */
  id?: string;
}

// ── Static LkSG categories (fallback) ─────────────────────────

const LKSG_CATEGORY_KEYS: LkSGCategory[] = [
  'child_labor',
  'forced_labor',
  'discrimination',
  'freedom_of_association',
  'working_conditions',
  'fair_wages',
  'environmental_damage',
  'land_rights',
  'security_forces',
  'other_human_rights',
  'other_environmental',
];

// ── API fetch for dynamic categories ──────────────────────────

interface APICategoryResponse {
  key: string;
  label: string;
}

async function fetchCategories(
  channel: Channel,
  language: string,
): Promise<CategoryOption[]> {
  const response = await apiClient.get<APICategoryResponse[]>(
    '/categories',
    { params: { channel, language } },
  );
  return response.data.map((cat) => ({
    value: cat.key,
    label: cat.label,
  }));
}

// ── Component ─────────────────────────────────────────────────

export default function CategorySelect({
  channel,
  value,
  onChange,
  error,
  disabled = false,
  id = 'category-select',
}: CategorySelectProps) {
  const { t, i18n } = useTranslation('report');
  const errorId = `${id}-error`;

  // Fetch categories from the API
  const { data: apiCategories } = useQuery<CategoryOption[]>({
    queryKey: ['categories', channel, i18n.language],
    queryFn: () => fetchCategories(channel, i18n.language),
    staleTime: 10 * 60 * 1000, // 10 minutes
    retry: 1,
  });

  // Build options: prefer API categories, fall back to i18n-translated static categories
  const options: CategoryOption[] = apiCategories ?? (
    channel === 'lksg'
      ? LKSG_CATEGORY_KEYS.map((key) => ({
          value: key,
          label: t(`categories.lksg.${key}`, key),
        }))
      : [] // HinSchG categories are fully API-driven (tenant-specific)
  );

  return (
    <div className="w-full">
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-neutral-700"
      >
        {t('fields.category', 'Kategorie')}
        {channel === 'lksg' && (
          <span className="ml-1 text-danger" aria-hidden="true">
            *
          </span>
        )}
      </label>

      <select
        id={id}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-describedby={error ? errorId : undefined}
        aria-invalid={error ? true : undefined}
        aria-required={channel === 'lksg'}
        className={`w-full rounded-lg border px-3 py-2.5 text-sm text-neutral-900 transition-colors ${
          error
            ? 'border-danger focus:border-danger focus:ring-danger'
            : 'border-neutral-300 focus:border-primary focus:ring-primary'
        } bg-white focus:ring-2 focus:ring-offset-0 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-neutral-500`}
      >
        <option value="">
          {t('fields.category_placeholder', '-- Kategorie auswählen --')}
        </option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      {error && (
        <p id={errorId} className="mt-1.5 text-sm text-danger" role="alert">
          {t(error, error)}
        </p>
      )}
    </div>
  );
}
