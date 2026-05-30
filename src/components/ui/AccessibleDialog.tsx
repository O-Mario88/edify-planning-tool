"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "motion/react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// Accessible dialog/drawer primitive used everywhere modal-y in the app.
//
// Guarantees:
//   • role="dialog" + aria-modal="true"
//   • aria-labelledby wired to the rendered title
//   • Focus trapped inside the dialog while open
//   • ESC closes (unless `dismissOnEscape={false}`)
//   • Overlay click closes (unless `dismissOnOverlayClick={false}`)
//   • Returns focus to the trigger element on close
//   • Body scroll locked while open
//
// Two visual variants:
//   • variant="dialog" — centered modal card (default)
//   • variant="drawer-right" — right-side panel (used for AddPlan etc.)
//   • variant="sheet" — bottom sheet on mobile, centered dialog on ≥md.
//     Sticky action footer slot, full-height-when-needed, safe-area
//     padding so the keyboard never hides the submit button.
//
// Renders into a portal so the dialog escapes any transformed parents.

type Variant = "dialog" | "drawer-right" | "sheet";

export function AccessibleDialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  variant = "dialog",
  size = "md",
  initialFocusRef,
  dismissOnEscape = true,
  dismissOnOverlayClick = true,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  variant?: Variant;
  size?: "sm" | "md" | "lg" | "xl";
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  dismissOnEscape?: boolean;
  dismissOnOverlayClick?: boolean;
  className?: string;
}) {
  const titleId = useId();
  const descId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  // Remember the focused element when opened so we can restore later.
  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    return () => {
      // Restore focus to the trigger
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

  // Body-scroll lock.
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
    const root = dialogRef.current;
    if (!root) return;

    const focusables = () =>
      Array.from(
        root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("inert") && el.offsetParent !== null);

    // Move initial focus.
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
  }, [open, initialFocusRef]);

  const overlayClick = useCallback(() => {
    if (dismissOnOverlayClick) onClose();
  }, [dismissOnOverlayClick, onClose]);

  if (typeof document === "undefined") return null;

  const sizeClass =
    size === "sm" ? "max-w-md" :
    size === "lg" ? "max-w-3xl" :
    size === "xl" ? "max-w-5xl" :
                    "max-w-xl";

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className={cn(
            "fixed inset-0 z-[1000] flex justify-center bg-black/45 backdrop-blur-[2px]",
            // Sheet sits at the bottom on mobile; centered on md+.
            // Drawer + dialog keep their existing alignment.
            variant === "sheet"
              ? "items-end md:items-center"
              : "items-stretch md:items-center",
          )}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={overlayClick}
          role="presentation"
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            initial={
              variant === "drawer-right"
                ? { x: "100%", opacity: 0 }
                : variant === "sheet"
                  ? { y: "100%", opacity: 0 }
                  : { y: 16, opacity: 0, scale: 0.98 }
            }
            animate={
              variant === "drawer-right"
                ? { x: 0, opacity: 1 }
                : variant === "sheet"
                  ? { y: 0, opacity: 1 }
                  : { y: 0, opacity: 1, scale: 1 }
            }
            exit={
              variant === "drawer-right"
                ? { x: "100%", opacity: 0 }
                : variant === "sheet"
                  ? { y: "100%", opacity: 0 }
                  : { y: 12, opacity: 0, scale: 0.98 }
            }
            transition={{ type: "spring", stiffness: 280, damping: 28 }}
            className={cn(
              // `premium-modal` / `premium-drawer` opt this surface into
              // the Glass-theme backdrop-blur + cyan-edge treatment (no
              // effect in light or dark; the class is purely a hook).
              variant === "drawer-right" ? "premium-drawer" : "premium-modal",
              "relative bg-[var(--surface-modal)] text-[var(--text-primary)] shadow-2xl border border-[var(--border-card)] focus:outline-none flex flex-col",
              variant === "drawer-right"
                ? "ml-auto h-full w-full md:max-w-[520px] md:rounded-l-2xl"
                : variant === "sheet"
                  // Sheet = full-height bottom sheet on mobile, centered
                  // dialog on md+. Safe-area padding keeps the keyboard
                  // from hiding the sticky action footer.
                  ? `mt-auto md:mt-0 md:mx-auto w-full ${sizeClass} rounded-t-2xl md:rounded-2xl max-h-[92vh] md:max-h-[90vh] pb-[env(safe-area-inset-bottom,0)]`
                  : `mx-3 md:mx-auto w-full ${sizeClass} rounded-2xl max-h-[90vh]`,
              className,
            )}
          >
            <header className="flex items-start gap-3 p-4 pb-3 border-b border-[var(--color-edify-border)]">
              <div className="min-w-0 flex-1">
                <h2 id={titleId} className="text-[15px] font-extrabold tracking-tight leading-tight">
                  {title}
                </h2>
                {description && (
                  <p id={descId} className="text-[12px] muted leading-snug mt-0.5">
                    {description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close dialog"
                className="h-8 w-8 rounded-md hover:bg-[var(--color-edify-soft)]/70 grid place-items-center text-[var(--color-edify-muted)] shrink-0"
              >
                <X size={16} />
              </button>
            </header>
            <div className="overflow-y-auto p-4 flex-1">{children}</div>
            {footer && (
              <footer className="border-t border-[var(--color-edify-border)] p-3 bg-[var(--color-edify-soft)]/30">
                {footer}
              </footer>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
