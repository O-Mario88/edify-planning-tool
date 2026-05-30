"use client";

import { useEffect, useRef } from "react";

// Retrofit hook for existing custom drawers/modals. Adds ESC-to-close,
// focus trap, return-focus-to-trigger, and body-scroll-lock without
// rebuilding the drawer markup. Pair with role="dialog", aria-modal,
// and aria-labelledby on the drawer's outer element.
//
// Usage:
//   const ref = useRef<HTMLElement | null>(null);
//   useDialogA11y({ open, onClose, containerRef: ref });
//   <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}>...</aside>
export function useDialogA11y({
  open,
  onClose,
  containerRef,
  initialFocusRef,
  dismissOnEscape = true,
}: {
  open: boolean;
  onClose: () => void;
  containerRef: React.RefObject<HTMLElement | null>;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  dismissOnEscape?: boolean;
}) {
  const returnFocusRef = useRef<HTMLElement | null>(null);

  // Capture the previously focused element so we can restore on close.
  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    return () => {
      returnFocusRef.current?.focus?.();
    };
  }, [open]);

  // ESC handler.
  useEffect(() => {
    if (!open || !dismissOnEscape) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, dismissOnEscape, onClose]);

  // Body scroll lock.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Initial focus + Tab trap.
  useEffect(() => {
    if (!open) return;
    const root = containerRef.current;
    if (!root) return;

    const focusables = () =>
      Array.from(
        root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("inert") && el.offsetParent !== null);

    const target = initialFocusRef?.current ?? focusables()[0] ?? root;
    target?.focus?.();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      const list = focusables();
      if (list.length === 0) {
        e.preventDefault();
        return;
      }
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    root.addEventListener("keydown", onKeyDown);
    return () => root.removeEventListener("keydown", onKeyDown);
  }, [open, containerRef, initialFocusRef]);
}
