import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// Tile — the canonical KPI / stat / metric tile.
//
// Codifies the /approvals page's KPI tile pattern so every role's
// dashboard uses the same surface for its headline metrics. Before
// this, each dashboard had a slightly different KPI tile (different
// padding, different hover treatment, different number sizing). After
// this, they share one definition.
//
// Visual contract (matches /approvals FundApprovalsKpiRow exactly):
//
//   .card                       — base white surface + border + shadow
//   .card-lift                  — lift + shadow + brand-tinted border on hover
//   .tile-in + .stagger-N       — fade-rise entrance, delayed per index
//   p-3                         — tight padding (vs the older p-4)
//   icon: w-9 h-9 rounded-full  — tinted circle, lucide icon size=15
//   label: 10px / muted / bold / uppercase tracking-wide / line-clamp-2
//   value: 18px / extrabold / tabular / num-hero / optional .glow-*
//   trend: 11.5px / colored arrow + delta
//
// Use `href` for clickable tiles (renders a Link, cursor-pointer);
// omit for static stat tiles (cursor-default).
//
// To match the stagger-animation rhythm, pass `index` (0-based) and
// the component picks the matching `.stagger-N` class. Tiles past
// index 7 fall back to no delay.

export type TileTone =
  | "edify"
  | "emerald"
  | "amber"
  | "rose"
  | "violet"
  | "sky"
  | "slate";

const TONE_BG: Record<TileTone, string> = {
  edify:   "bg-[var(--color-edify-soft)]",
  emerald: "bg-emerald-100 dark:bg-emerald-500/15",
  amber:   "bg-amber-100   dark:bg-amber-500/15",
  rose:    "bg-rose-100    dark:bg-rose-500/15",
  violet:  "bg-violet-100  dark:bg-violet-500/15",
  sky:     "bg-sky-100     dark:bg-sky-500/15",
  slate:   "bg-slate-100   dark:bg-slate-500/15",
};

const TONE_FG: Record<TileTone, string> = {
  edify:   "text-[var(--color-edify-primary)]",
  emerald: "text-emerald-700 dark:text-emerald-300",
  amber:   "text-amber-700   dark:text-amber-300",
  rose:    "text-rose-600    dark:text-rose-300",
  violet:  "text-violet-700  dark:text-violet-300",
  sky:     "text-sky-700     dark:text-sky-300",
  slate:   "text-slate-600   dark:text-slate-300",
};

const TONE_GLOW: Record<TileTone, string> = {
  edify:   "glow-slate",
  emerald: "glow-emerald",
  amber:   "glow-amber",
  rose:    "glow-rose",
  violet:  "glow-slate",
  sky:     "glow-slate",
  slate:   "glow-slate",
};

const STAGGER = [
  "stagger-1", "stagger-2", "stagger-3", "stagger-4",
  "stagger-5", "stagger-6", "stagger-7", "stagger-8",
];

export function Tile({
  label,
  value,
  trend,
  icon,
  tone = "edify",
  href,
  index,
  className,
}: {
  label:    ReactNode;
  value:    ReactNode;
  /** Optional trailing line under the value (e.g. "+6.6% vs Apr"). */
  trend?:   ReactNode;
  /** Lucide icon node, rendered inside the tinted circle. */
  icon?:    ReactNode;
  tone?:    TileTone;
  /** Pass an href to make the tile clickable (renders as <Link>). */
  href?:    string;
  /** Stagger-animation index. Omit for no delay. */
  index?:   number;
  className?: string;
}) {
  const Inner = href ? Link : "div";
  const innerProps = href
    ? { href, className: "block" }
    : ({} as Record<string, never>);

  const cursor = href ? "cursor-pointer" : "cursor-default";
  const stagger = typeof index === "number" ? STAGGER[index] ?? "" : "";

  return (
    <Inner
      {...innerProps}
      className={cn(
        "card card-lift tile-in p-3",
        cursor,
        stagger,
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        {icon ? (
          <span className={cn(
            "w-9 h-9 rounded-full grid place-items-center shrink-0",
            TONE_BG[tone],
            TONE_FG[tone],
          )}>
            {icon}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2">
            {label}
          </div>
        </div>
      </div>

      <div className={cn(
        "text-[18px] font-extrabold tabular leading-none mt-2.5 text-[var(--text-primary)] num-hero",
        TONE_GLOW[tone],
      )}>
        {value}
      </div>

      {trend ? (
        <div className="t-caption font-semibold mt-1.5 leading-snug">
          {trend}
        </div>
      ) : null}
    </Inner>
  );
}
