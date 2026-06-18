import { type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Lock, Sparkles, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// ProductiveEmptyState — the centered, full-bleed empty state for routes that
// have NO content yet (genuinely empty, or gated off mock data in production).
//
// Design intent (the "don't shrink-wrap the void" rule): a withheld or empty
// page should NOT collapse to a lonely card stranded at the top — that reads as
// broken. It should center a calm, intentional panel in the available space and
// turn the void into a NEXT STEP: a leading icon, an honest headline, one line
// of context, a primary action, and a couple of escape-hatch links. Premium
// products (Stripe, Linear, Vercel) treat the empty state as onboarding, not an
// error. Honest by design — it never fabricates a number to fill space.
//
//   <ProductiveEmptyState
//     Icon={ClipboardCheck}
//     title="No evidence in your queue yet"
//     description="When you complete a visit and upload proof, it lands here for IA review."
//     actionLabel="Schedule a visit" actionHref="/my-plan"
//     links={[{ label: "View data quality", href: "/analytics/data-room" }]}
//     note="Figures are withheld until they trace to live source records."
//   />
//
// For SECONDARY (inside-a-section) empty surfaces use the compact
// `InsufficientData` / `EmptyState` instead — this one owns the whole page.

export type EmptyTone = "info" | "neutral" | "warn" | "success" | "violet";

const TONE: Record<EmptyTone, string> = {
  info:    "bg-blue-100 text-blue-600 dark:text-blue-300",
  neutral: "bg-slate-100 text-slate-500",
  warn:    "bg-amber-100 text-amber-600 dark:text-amber-300",
  success: "bg-emerald-100 text-emerald-600 dark:text-emerald-300",
  violet:  "bg-violet-100 text-violet-600 dark:text-violet-300",
};

export function ProductiveEmptyState({
  Icon = Sparkles,
  title,
  description,
  tone = "info",
  /** Primary CTA shortcut — renders a brand button linking to actionHref. */
  actionLabel,
  actionHref,
  /** Pre-built primary action (e.g. a drawer trigger). Overrides actionLabel. */
  action,
  /** Secondary escape-hatch links rendered as quiet buttons. */
  links = [],
  /** Small muted footnote — used for the honest "why withheld" line. */
  note,
  className,
}: {
  Icon?: LucideIcon;
  title: string;
  description?: string;
  tone?: EmptyTone;
  actionLabel?: string;
  actionHref?: string;
  action?: ReactNode;
  links?: { label: string; href: string }[];
  note?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        // Fills the content area so the panel centers in the viewport (minus
        // the page header) — intentional calm, not a card stranded at the top.
        "flex flex-col items-center justify-center text-center",
        "min-h-[52vh] md:min-h-[58vh] px-4 py-10",
        className,
      )}
    >
      <span
        className={cn(
          "h-14 w-14 rounded-2xl grid place-items-center mb-4 shrink-0",
          TONE[tone],
        )}
      >
        <Icon size={26} strokeWidth={1.75} />
      </span>

      <h2 className="text-[17px] md:text-[18px] font-semibold tracking-tight leading-tight max-w-md">
        {title}
      </h2>

      {description && (
        <p className="text-[13px] text-secondary leading-relaxed mt-2 max-w-sm">
          {description}
        </p>
      )}

      {(action || (actionLabel && actionHref) || links.length > 0) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5">
          {action
            ? action
            : actionLabel && actionHref && (
                <Link href={actionHref} className="btn btn-primary inline-flex items-center gap-1.5">
                  {actionLabel}
                  <ArrowRight size={15} />
                </Link>
              )}
          {links.map((l) => (
            <Link key={l.href + l.label} href={l.href} className="btn btn-sm">
              {l.label}
            </Link>
          ))}
        </div>
      )}

      {note && (
        <p className="text-[11.5px] muted mt-5 max-w-sm inline-flex items-start gap-1.5 leading-snug">
          <Lock size={12} className="mt-0.5 shrink-0" />
          <span>{note}</span>
        </p>
      )}
    </div>
  );
}
