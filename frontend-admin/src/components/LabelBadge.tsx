/**
 * Hinweisgebersystem – LabelBadge Component.
 *
 * Renders a colour-coded pill/badge for displaying report labels.
 * The background uses the label's hex colour at reduced opacity,
 * with the label name in a readable foreground colour derived from
 * the background luminance.
 *
 * Used in case lists, case detail views, and the label manager to
 * provide consistent visual identification of labels.
 *
 * Uses semantic HTML with ARIA for accessibility.
 */

import { useMemo } from 'react';

// ── Types ─────────────────────────────────────────────────────

interface LabelBadgeProps {
  /** Label display name. */
  name: string;
  /** Hex colour code (e.g. "#FF5733"). */
  color: string;
  /** Optional click handler (e.g. for removal). */
  onRemove?: () => void;
  /** Size variant. */
  size?: 'sm' | 'md';
}

// ── Colour Helpers ────────────────────────────────────────────

/**
 * Parse a hex colour string into RGB components.
 * Supports both 3-digit (#RGB) and 6-digit (#RRGGBB) formats.
 */
function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const sanitised = hex.replace('#', '');

  if (sanitised.length === 3) {
    return {
      r: parseInt(sanitised[0] + sanitised[0], 16),
      g: parseInt(sanitised[1] + sanitised[1], 16),
      b: parseInt(sanitised[2] + sanitised[2], 16),
    };
  }

  return {
    r: parseInt(sanitised.substring(0, 2), 16),
    g: parseInt(sanitised.substring(2, 4), 16),
    b: parseInt(sanitised.substring(4, 6), 16),
  };
}

/**
 * Calculate relative luminance of a colour using the sRGB formula.
 * Returns a value between 0 (darkest) and 1 (lightest).
 */
function getLuminance(r: number, g: number, b: number): number {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const srgb = c / 255;
    return srgb <= 0.03928
      ? srgb / 12.92
      : Math.pow((srgb + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

/**
 * Determine whether to use dark or light foreground text
 * based on the background colour's luminance.
 */
function getContrastColor(hex: string): string {
  const { r, g, b } = hexToRgb(hex);
  const luminance = getLuminance(r, g, b);
  // WCAG contrast threshold — use dark text on light backgrounds
  return luminance > 0.4 ? '#1f2937' : '#ffffff';
}

// ── Component ────────────────────────────────────────────────

/**
 * Colour-coded label badge/pill.
 *
 * Renders the label name inside a rounded pill with the label's
 * colour as background (at reduced opacity for readability).
 * An optional remove button (×) is shown when `onRemove` is provided.
 */
export default function LabelBadge({
  name,
  color,
  onRemove,
  size = 'sm',
}: LabelBadgeProps) {
  const { bgStyle, textColor } = useMemo(() => {
    const { r, g, b } = hexToRgb(color);
    return {
      bgStyle: {
        backgroundColor: `rgba(${r}, ${g}, ${b}, 0.15)`,
        borderColor: `rgba(${r}, ${g}, ${b}, 0.3)`,
      },
      textColor: getContrastColor(color),
    };
  }, [color]);

  const sizeClasses = size === 'sm'
    ? 'px-2 py-0.5 text-xs'
    : 'px-2.5 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border font-medium ${sizeClasses}`}
      style={{ ...bgStyle, color: textColor }}
      title={name}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: color }}
        aria-hidden="true"
      />
      {name}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-black/10"
          aria-label={`Remove label ${name}`}
        >
          <svg
            className="h-3 w-3"
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
      )}
    </span>
  );
}
