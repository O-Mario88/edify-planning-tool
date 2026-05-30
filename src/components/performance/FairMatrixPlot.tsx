"use client";

// Fair Matrix Plot — the 2×2 scatter that replaces the ranked-staff
// leaderboard with a Performance-in-Context view.
//
// X-axis: Portfolio Complexity Percentile (0 = lightest, 1 = heaviest)
// Y-axis: Raw target completion %
//
// Quadrants:
//   Top-left   = Consistent          (high pace, low load)
//   Top-right  = True Top Performer  (high pace, high load)
//   Bottom-right = Overloaded         (low/medium pace, high load)
//   Bottom-left  = Concern            (low pace, low load)
//
// Each staff is a dot, tinted by their assigned band. Hovering shows
// a mini profile card with the band reason.

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { fadeUp, spring, staggerContainer } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { BAND_LABEL, BAND_TONE, type FairMatrixRow } from "@/lib/performance/fwi-types";

const TONE_BG: Record<ReturnType<typeof toneFor>, string> = {
  emerald: "bg-emerald-500",
  sky:     "bg-sky-500",
  amber:   "bg-amber-500",
  rose:    "bg-rose-500",
  violet:  "bg-violet-500",
  slate:   "bg-slate-400",
};
const TONE_RING: Record<ReturnType<typeof toneFor>, string> = {
  emerald: "ring-emerald-200",
  sky:     "ring-sky-200",
  amber:   "ring-amber-200",
  rose:    "ring-rose-200",
  violet:  "ring-violet-200",
  slate:   "ring-slate-200",
};
const TONE_CHIP: Record<ReturnType<typeof toneFor>, string> = {
  emerald: "bg-emerald-50  text-emerald-700  border-emerald-200",
  sky:     "bg-sky-50      text-sky-700      border-sky-200",
  amber:   "bg-amber-50    text-amber-700    border-amber-200",
  rose:    "bg-rose-50     text-rose-700     border-rose-200",
  violet:  "bg-violet-50   text-violet-700   border-violet-200",
  slate:   "bg-slate-50    text-slate-700    border-slate-200",
};

function toneFor(row: FairMatrixRow): "emerald" | "sky" | "amber" | "rose" | "violet" | "slate" {
  return BAND_TONE[row.band];
}

export function FairMatrixPlot({ rows }: { rows: FairMatrixRow[] }) {
  const reduce = useReducedMotion();
  const [hovered, setHovered] = useState<FairMatrixRow | null>(null);

  return (
    <section className="card p-3.5 sm:p-5">
      <header className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-xl bg-violet-50 grid place-items-center text-violet-600 shrink-0">
          <Sparkles size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight">Performance in context</h3>
          <p className="text-[12px] muted leading-snug mt-0.5">
            Output measured against portfolio difficulty — so a 100% on a light portfolio doesn&apos;t outrank an 85% on a heavy one.
          </p>
        </div>
      </header>

      {/* Plot area — 2×2 grid with quadrant labels, dot per staff. */}
      <div className="relative w-full aspect-[4/3] sm:aspect-[2/1] border border-[var(--color-edify-border)] rounded-xl overflow-hidden bg-gradient-to-br from-white via-white to-slate-50">
        {/* Quadrant dividers */}
        <div className="absolute inset-y-0 left-1/2 w-px bg-[var(--color-edify-border)]" aria-hidden />
        <div className="absolute inset-x-0 top-1/2 h-px bg-[var(--color-edify-border)]" aria-hidden />

        {/* Axis labels */}
        <div className="absolute top-2 left-2 text-[10px] font-bold uppercase tracking-wider text-[var(--color-edify-muted)]">
          High Pace
        </div>
        <div className="absolute bottom-2 left-2 text-[10px] font-bold uppercase tracking-wider text-[var(--color-edify-muted)]">
          Low Pace
        </div>
        <div className="absolute top-2 right-2 text-[10px] font-bold uppercase tracking-wider text-[var(--color-edify-muted)]">
          ← Heavy Load
        </div>
        <div className="absolute bottom-2 right-2 text-[10px] font-bold uppercase tracking-wider text-[var(--color-edify-muted)]">
          Light Load →
        </div>

        {/* Quadrant labels (subtle, behind dots) */}
        <QuadrantLabel position="tl" label="Consistent" tone="sky" />
        <QuadrantLabel position="tr" label="True Top Performer" tone="emerald" />
        <QuadrantLabel position="bl" label="Coaching Conversation" tone="rose" />
        <QuadrantLabel position="br" label="Carrying Heavy Load" tone="amber" />

        {/* Dots */}
        <motion.div
          variants={staggerContainer(0.06, 0.04)}
          initial="hidden"
          animate="visible"
          className="absolute inset-0"
        >
          {rows.map((r) => {
            // x: complexityPercentile (0 lightest = far right, 1 heaviest = far left in our reading order).
            // Actually we want heavy load → right side (matches reading order). So x = percentile.
            const x = clamp(r.complexityPercentile, 0, 1);
            const y = clamp(r.adjustedPacePct / 100, 0, 1);
            // Convert to %; pad 4% on each side so dots don't touch the frame.
            const left = `${4 + x * 92}%`;
            const top = `${4 + (1 - y) * 92}%`;
            return (
              <motion.button
                key={r.staffId}
                type="button"
                variants={fadeUp}
                transition={reduce ? { duration: 0 } : spring.soft}
                onMouseEnter={() => setHovered(r)}
                onFocus={() => setHovered(r)}
                onMouseLeave={() => setHovered(null)}
                onBlur={() => setHovered(null)}
                className={cn(
                  "absolute -translate-x-1/2 -translate-y-1/2",
                  "h-9 w-9 rounded-full text-white text-[11px] font-extrabold grid place-items-center shadow-sm ring-4 outline-none focus-visible:ring-offset-2",
                  TONE_BG[toneFor(r)],
                  TONE_RING[toneFor(r)],
                )}
                style={{ left, top }}
                aria-label={`${r.staffName}: ${BAND_LABEL[r.band]}, ${r.rawPacePct}% pace`}
              >
                {r.initials}
              </motion.button>
            );
          })}
        </motion.div>
      </div>

      {/* Hover detail strip — never empty (shows a prompt when nothing is hovered) */}
      <div className="mt-3 min-h-[68px] rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3 py-2.5">
        {hovered ? (
          <div className="flex items-start gap-3">
            <div className={cn(
              "h-9 w-9 rounded-full text-white text-[11px] font-extrabold grid place-items-center shrink-0",
              TONE_BG[toneFor(hovered)],
            )}>
              {hovered.initials}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[13px] font-extrabold tracking-tight">{hovered.staffName}</span>
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[1px] rounded-md text-caption font-bold border",
                  TONE_CHIP[toneFor(hovered)],
                )}>
                  {BAND_LABEL[hovered.band]}
                </span>
                <span className="text-caption muted">
                  pace {hovered.rawPacePct}% · adjusted {hovered.adjustedPacePct}% · load {hovered.complexityScore.toFixed(1)}
                </span>
              </div>
              <p className="text-[11.5px] muted leading-snug mt-1">{hovered.bandReason}</p>
            </div>
          </div>
        ) : (
          <p className="text-[11.5px] muted">
            Hover a dot to see the staff member&apos;s band and why they sit where they do.
          </p>
        )}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-2">
        {Object.entries(BAND_LABEL).map(([band, label]) => (
          <span
            key={band}
            className={cn(
              "inline-flex items-center gap-1.5 px-2 py-[2px] rounded-md text-[10px] font-bold border",
              TONE_CHIP[BAND_TONE[band as keyof typeof BAND_TONE]],
            )}
          >
            <span className={cn("w-2 h-2 rounded-full", TONE_BG[BAND_TONE[band as keyof typeof BAND_TONE]])} aria-hidden />
            {label}
          </span>
        ))}
      </div>
    </section>
  );
}

function QuadrantLabel({
  position,
  label,
  tone,
}: {
  position: "tl" | "tr" | "bl" | "br";
  label: string;
  tone: "emerald" | "sky" | "amber" | "rose";
}) {
  const pos = {
    tl: "top-8 left-8 text-left",
    tr: "top-8 right-8 text-right",
    bl: "bottom-8 left-8 text-left",
    br: "bottom-8 right-8 text-right",
  }[position];
  const toneCls = {
    emerald: "text-emerald-500/60",
    sky:     "text-sky-500/60",
    amber:   "text-amber-600/60",
    rose:    "text-rose-500/60",
  }[tone];
  return (
    <div className={cn(
      "absolute pointer-events-none text-[11px] font-extrabold tracking-tight max-w-[40%] leading-tight",
      pos,
      toneCls,
    )}>
      {label}
    </div>
  );
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n));
}
