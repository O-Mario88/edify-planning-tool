import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// SectionHeader — the canonical card / rail header.
//
// Picks one of three typographic tiers so the dashboard reads with
// hierarchy instead of a flat row of equal-weight titles:
//
//   • strategic   — hero rails, primary analytics rows. Comes with an
//                   optional uppercase eyebrow above the title for a
//                   two-line "category → name" rhythm.
//   • operational — the default card title (tables, lists, panels).
//   • micro       — sub-block headings INSIDE a card / rail.
//
// `icon`  — small leading badge (Lucide icon already wrapped in the
//           caller's color treatment).
// `meta`  — right-aligned trailing slot (count, action link, dropdown).
// `description` — optional one-liner under the title, only meaningful
//           on the strategic tier; on operational it's noise.

type Tier = "strategic" | "operational" | "micro";

const TIER_CLASS: Record<Tier, string> = {
  strategic:   "section-h-strategic",
  operational: "section-h-operational",
  micro:       "section-h-micro",
};

export function SectionHeader({
  tier = "operational",
  eyebrow,
  title,
  description,
  icon,
  meta,
  className,
  as: As = "h2",
}: {
  tier?:        Tier;
  eyebrow?:     string;
  title:        ReactNode;
  description?: ReactNode;
  icon?:        ReactNode;
  meta?:        ReactNode;
  className?:   string;
  as?:          "h1" | "h2" | "h3";
}) {
  return (
    <header className={cn("flex items-start gap-3", className)}>
      {icon ? <span className="shrink-0 mt-0.5">{icon}</span> : null}
      <div className="flex-1 min-w-0">
        {eyebrow ? (
          <p className="eyebrow mb-1">{eyebrow}</p>
        ) : null}
        <As className={TIER_CLASS[tier]}>{title}</As>
        {description ? (
          <p className="t-body text-secondary mt-1">{description}</p>
        ) : null}
        {/* Narrow screens: meta drops below the title so it never squeezes the
            title column into a per-word wrap. */}
        {meta ? <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">{meta}</div> : null}
      </div>
      {meta ? <div className="hidden sm:block shrink-0 ml-auto">{meta}</div> : null}
    </header>
  );
}
