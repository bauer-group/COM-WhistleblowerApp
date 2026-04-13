/**
 * Hinweisgebersystem – Dialog Accessibility Hook.
 *
 * Provides Escape key handling and focus trapping for modal dialogs
 * to comply with WCAG 2.1 AA (SC 2.1.2 – No Keyboard Trap).
 */

import { useEffect, useRef } from 'react';

/**
 * Hook that provides a ref and a11y behaviours for modal dialogs.
 *
 * - Closes the dialog when Escape is pressed.
 * - Traps focus within the dialog (Tab / Shift+Tab cycle).
 * - Auto-focuses the first focusable element on open.
 *
 * @param isOpen  Whether the dialog is currently visible.
 * @param onClose Callback to close the dialog.
 */
export function useDialogA11y(isOpen: boolean, onClose: () => void) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }

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

    // Auto-focus the first focusable element.
    const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    firstFocusable?.focus();

    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  return dialogRef;
}
