"use client";

// BackButton — the leading affordance for "return to previous page".
//
// Multi-billion product design call: back lives top-left of the page
// *content*, before the title, in a leading slot. Reasoning:
//   • F-pattern reading → eye lands top-left first
//   • Matches iOS / Material / Stripe / Linear / Notion conventions
//   • Sits inside the page content so it reads as "back from this
//     surface" — not chrome / global nav
//   • On mobile the hamburger lives in the *fixed* layer above; the
//     PageHeader's `pl-12 lg:pl-0` keeps room for both
//
// Smart behaviour:
//   • Click: try router.back() if there's a history entry to return to,
//     otherwise fall back to `fallbackHref` (the structural parent of
//     this surface — e.g. /schools for /schools/[id]).
//   • If `fallbackHref` is omitted and there's no history, the button
//     hides itself rather than become a dead click.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";

export type BackButtonProps = {
  /** Where to go if browser history is empty (deep-link / hard reload).
   *  Default: omit — the button auto-hides instead of dead-clicking. */
  fallbackHref?: string;
  /** Override the default aria-label. */
  label?:    string;
  /** Compact size for tight headers. Default `md` (h-9). */
  size?:     "sm" | "md";
  className?: string;
};

export function BackButton({
  fallbackHref,
  label = "Go back",
  size = "md",
  className,
}: BackButtonProps) {
  const router = useRouter();
  // We hydrate-and-check rather than relying on history during SSR
  // (window is undefined on the server). The button renders a hidden
  // shell on the first paint, then reveals once we know whether there's
  // a history entry to return to.
  const [hasHistory, setHasHistory] = useState(false);

  useEffect(() => {
    // Browser-only check that must be deferred past hydration to avoid
    // SSR/client mismatch. Migrate to useSyncExternalStore when the
    // React-19 sweep lands.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHasHistory(typeof window !== "undefined" && window.history.length > 1);
  }, []);

  // If there's no history and no fallback, the button has nothing
  // useful to do — hide it rather than show a dead click.
  if (!hasHistory && !fallbackHref) return null;

  const sizing = size === "sm"
    ? "h-8 w-8 rounded-lg"
    : "h-9 w-9 rounded-xl";

  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        if (hasHistory) {
          router.back();
        } else if (fallbackHref) {
          router.push(fallbackHref);
        }
      }}
      className={cn(
        "grid place-items-center shrink-0 bg-[var(--color-card)] border border-[var(--color-edify-border)] text-[var(--color-edify-muted)] shadow-[0_1px_2px_var(--shadow-card-contact)] hover:bg-[var(--color-edify-soft)] hover:text-[var(--color-edify-text)] transition-colors",
        sizing,
        className,
      )}
    >
      <ChevronLeft size={size === "sm" ? 15 : 16} />
    </button>
  );
}
