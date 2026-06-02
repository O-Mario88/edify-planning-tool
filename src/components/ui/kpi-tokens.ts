// kpi-tokens — the single source of truth for KPI/stat tile visual tokens.
//
// Before this module, every role's *KpiRow component re-declared its own
// `tone → { bg, fg, glow }` maps and its own stagger array. That was the real
// duplication behind the "18 KPI variants" finding — not the rows themselves
// (which legitimately differ: some carry progress rings, sparklines, or a flat
// stat-bar layout), but the copy-pasted colour tables inside each one.
//
// Centralising them here means:
//   • one place to tune the KPI palette,
//   • consistent light / dark / glass behaviour (every tone ships a `dark:`
//     variant, so KPI tiles never break in the non-light themes), and
//   • legacy tone aliases (green/red/blue) normalise to the canonical set,
//     so rows can adopt the shared tokens without touching their mock data.

export type KpiTone =
  | "edify"
  | "emerald"
  | "amber"
  | "rose"
  | "violet"
  | "sky"
  | "slate";

// Legacy aliases used across older rows → canonical tone.
const TONE_ALIAS: Record<string, KpiTone> = {
  green: "emerald",
  red:   "rose",
  blue:  "sky",
};

/** Normalise any tone string (incl. legacy aliases) to a canonical KpiTone. */
export function kpiTone(tone: string): KpiTone {
  return (TONE_ALIAS[tone] ?? tone) as KpiTone;
}

/** Tinted icon-circle background per tone (light + dark/glass). */
export const KPI_ICON_BG: Record<KpiTone, string> = {
  edify:   "bg-[var(--color-edify-soft)]",
  emerald: "bg-emerald-100 dark:bg-emerald-500/15",
  amber:   "bg-amber-100   dark:bg-amber-500/15",
  rose:    "bg-rose-100    dark:bg-rose-500/15",
  violet:  "bg-violet-100  dark:bg-violet-500/15",
  sky:     "bg-sky-100     dark:bg-sky-500/15",
  slate:   "bg-slate-100   dark:bg-slate-500/15",
};

/** Icon foreground colour per tone (light + dark/glass). */
export const KPI_ICON_FG: Record<KpiTone, string> = {
  edify:   "text-[var(--color-edify-primary)]",
  emerald: "text-emerald-700 dark:text-emerald-300",
  amber:   "text-amber-700   dark:text-amber-300",
  rose:    "text-rose-600    dark:text-rose-300",
  violet:  "text-violet-700  dark:text-violet-300",
  sky:     "text-sky-700     dark:text-sky-300",
  slate:   "text-slate-600   dark:text-slate-300",
};

/** Combined `bg + fg` convenience (the most common pairing). */
export const KPI_ICON_TINT: Record<KpiTone, string> = Object.fromEntries(
  (Object.keys(KPI_ICON_BG) as KpiTone[]).map((t) => [
    t,
    `${KPI_ICON_BG[t]} ${KPI_ICON_FG[t]}`,
  ]),
) as Record<KpiTone, string>;

/** Number-glow accent per tone (maps to the global glow-* utilities). */
export const KPI_GLOW: Record<KpiTone, string> = {
  edify:   "glow-slate",
  emerald: "glow-emerald",
  amber:   "glow-amber",
  rose:    "glow-rose",
  violet:  "glow-slate",
  sky:     "glow-slate",
  slate:   "glow-slate",
};

/** Donut/ring stroke hex per signalling tone (for inline SVG rings). */
export const KPI_RING_STROKE: Record<"emerald" | "amber" | "rose", string> = {
  emerald: "#10b981",
  amber:   "#f59e0b",
  rose:    "#ef4444",
};

/** Stagger-animation classes, indexed 0-based. */
export const KPI_STAGGER = [
  "stagger-1", "stagger-2", "stagger-3", "stagger-4",
  "stagger-5", "stagger-6", "stagger-7", "stagger-8",
];

/** Stagger class for a 0-based index (empty string past the table). */
export function kpiStagger(index?: number): string {
  return typeof index === "number" ? KPI_STAGGER[index] ?? "" : "";
}
