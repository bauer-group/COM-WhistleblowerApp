/**
 * Hinweisgebersystem - CaptchaWidget Component.
 *
 * hCaptcha integration for bot protection on report submission.
 * Supports reset after form submission (tokens are one-time use).
 * Can be configured as invisible mode for Tor-friendly UX.
 *
 * IMPORTANT: hCaptcha script is loaded dynamically to avoid
 * third-party JS dependencies at page load time (Tor compatibility).
 *
 * WCAG 2.1 AA compliant:
 * - The hCaptcha widget natively provides accessibility features
 * - aria-label on the container for screen readers
 * - Status announcements via aria-live region
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';

// ── Types ──────────────────────────────────────────────────────

interface CaptchaWidgetProps {
  /** hCaptcha site key. Falls back to VITE_HCAPTCHA_SITEKEY env var. */
  siteKey?: string;
  /** Callback when the user completes the captcha. */
  onVerify: (token: string) => void;
  /** Callback when the captcha expires. */
  onExpire?: () => void;
  /** Callback when the captcha encounters an error. */
  onError?: (error: string) => void;
  /** hCaptcha size mode. Use "invisible" for Tor-friendly UX. */
  size?: 'normal' | 'compact' | 'invisible';
  /** hCaptcha theme. */
  theme?: 'light' | 'dark';
  /** Error message from form validation. */
  error?: string;
}

export interface CaptchaWidgetHandle {
  /** Reset the captcha widget (call after form submission). */
  resetCaptcha: () => void;
  /** Execute the captcha (for invisible mode). */
  executeCaptcha: () => void;
}

// ── hCaptcha global API types ─────────────────────────────────

interface HCaptchaAPI {
  render: (
    container: HTMLElement,
    params: {
      sitekey: string;
      callback: (token: string) => void;
      'expired-callback': () => void;
      'error-callback': (error: string) => void;
      size: string;
      theme: string;
    },
  ) => string;
  reset: (widgetId: string) => void;
  execute: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    hcaptcha?: HCaptchaAPI;
  }
}

// ── Script loader ─────────────────────────────────────────────

let scriptLoadPromise: Promise<void> | null = null;

function loadHCaptchaScript(): Promise<void> {
  if (window.hcaptcha) {
    return Promise.resolve();
  }

  if (scriptLoadPromise) {
    return scriptLoadPromise;
  }

  scriptLoadPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://js.hcaptcha.com/1/api.js?render=explicit';
    script.async = true;
    script.defer = true;

    script.onload = () => resolve();
    script.onerror = () => {
      scriptLoadPromise = null;
      reject(new Error('Failed to load hCaptcha script'));
    };

    document.head.appendChild(script);
  });

  return scriptLoadPromise;
}

// ── Component ─────────────────────────────────────────────────

const CaptchaWidget = forwardRef<CaptchaWidgetHandle, CaptchaWidgetProps>(
  function CaptchaWidget(
    {
      siteKey,
      onVerify,
      onExpire,
      onError,
      size = 'normal',
      theme = 'light',
      error,
    },
    ref,
  ) {
    const { t } = useTranslation('report');
    const containerRef = useRef<HTMLDivElement>(null);
    const widgetIdRef = useRef<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const resolvedSiteKey =
      siteKey ?? (import.meta.env.VITE_HCAPTCHA_SITEKEY as string | undefined) ?? '';

    const errorId = 'captcha-error';

    // Expose reset and execute methods via ref
    useImperativeHandle(ref, () => ({
      resetCaptcha: () => {
        if (widgetIdRef.current !== null && window.hcaptcha) {
          window.hcaptcha.reset(widgetIdRef.current);
        }
      },
      executeCaptcha: () => {
        if (widgetIdRef.current !== null && window.hcaptcha) {
          window.hcaptcha.execute(widgetIdRef.current);
        }
      },
    }));

    // Stable callback refs to avoid re-renders breaking hCaptcha
    const onVerifyRef = useRef(onVerify);
    const onExpireRef = useRef(onExpire);
    const onErrorRef = useRef(onError);

    useEffect(() => {
      onVerifyRef.current = onVerify;
    }, [onVerify]);

    useEffect(() => {
      onExpireRef.current = onExpire;
    }, [onExpire]);

    useEffect(() => {
      onErrorRef.current = onError;
    }, [onError]);

    // Load script and render widget
    useEffect(() => {
      if (!resolvedSiteKey) {
        setIsLoading(false);
        setLoadError('hCaptcha site key not configured');
        return;
      }

      let isMounted = true;

      loadHCaptchaScript()
        .then(() => {
          if (!isMounted || !containerRef.current || !window.hcaptcha) return;

          // Clear any previous widget
          if (widgetIdRef.current !== null) {
            try {
              window.hcaptcha.remove(widgetIdRef.current);
            } catch {
              // Widget may have been removed already
            }
          }

          const id = window.hcaptcha.render(containerRef.current, {
            sitekey: resolvedSiteKey,
            callback: (token: string) => onVerifyRef.current(token),
            'expired-callback': () => onExpireRef.current?.(),
            'error-callback': (err: string) => onErrorRef.current?.(err),
            size,
            theme,
          });

          widgetIdRef.current = id;
          setIsLoading(false);
        })
        .catch((err: Error) => {
          if (!isMounted) return;
          setLoadError(err.message);
          setIsLoading(false);
        });

      return () => {
        isMounted = false;
        // Cleanup widget on unmount
        if (widgetIdRef.current !== null && window.hcaptcha) {
          try {
            window.hcaptcha.remove(widgetIdRef.current);
          } catch {
            // Widget may have been removed already
          }
          widgetIdRef.current = null;
        }
      };
    }, [resolvedSiteKey, size, theme]);

    const handleRetry = useCallback(() => {
      setLoadError(null);
      setIsLoading(true);
      scriptLoadPromise = null;

      // Re-trigger the effect by updating state
      loadHCaptchaScript()
        .then(() => {
          if (!containerRef.current || !window.hcaptcha) return;

          const id = window.hcaptcha.render(containerRef.current, {
            sitekey: resolvedSiteKey,
            callback: (token: string) => onVerifyRef.current(token),
            'expired-callback': () => onExpireRef.current?.(),
            'error-callback': (err: string) => onErrorRef.current?.(err),
            size,
            theme,
          });

          widgetIdRef.current = id;
          setIsLoading(false);
        })
        .catch((err: Error) => {
          setLoadError(err.message);
          setIsLoading(false);
        });
    }, [resolvedSiteKey, size, theme]);

    return (
      <div className="w-full">
        <div
          aria-label={t('captcha.label', 'Bot-Schutz')}
          aria-describedby={error ? errorId : undefined}
        >
          {/* Loading state */}
          {isLoading && (
            <div
              className="flex h-[78px] items-center justify-center rounded-lg border border-neutral-200 bg-neutral-50"
              role="status"
            >
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="ml-2 text-sm text-neutral-500">
                {t('captcha.loading', 'Captcha wird geladen...')}
              </span>
            </div>
          )}

          {/* Error state */}
          {loadError && !isLoading && (
            <div
              className="flex flex-col items-center gap-2 rounded-lg border border-danger/30 bg-danger/5 px-4 py-3"
              role="alert"
            >
              <p className="text-sm text-danger">
                {t('captcha.load_error', 'Captcha konnte nicht geladen werden.')}
              </p>
              <button
                type="button"
                onClick={handleRetry}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-dark"
              >
                {t('captcha.retry', 'Erneut versuchen')}
              </button>
            </div>
          )}

          {/* hCaptcha render target */}
          <div
            ref={containerRef}
            className={isLoading || loadError ? 'hidden' : ''}
          />
        </div>

        {/* Validation error */}
        {error && (
          <p id={errorId} className="mt-1.5 text-sm text-danger" role="alert">
            {t(error, error)}
          </p>
        )}

        {/* Screen reader status */}
        <div className="sr-only" aria-live="polite">
          {isLoading && t('captcha.loading', 'Captcha wird geladen...')}
        </div>
      </div>
    );
  },
);

export default CaptchaWidget;
