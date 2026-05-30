"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { ProgressRing } from "@/components/ui/primitives";
import {
  targetCascade,
  type CascadeStatus,
  type CascadeTone,
  type TargetCascadeTile,
} from "@/lib/my-targets-billion-mock";
import { cn } from "@/lib/utils";

// 4-tier cascade — FY → Quarter → Month → Day. The defining visual of
// the My Targets dashboard: large UGX number on the left, progress
// ring on the right, status pill at the bottom. Subtle index chips
// hint at the funnel narrative (each tier nested inside the previous).
export function TargetCascadeRow() {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 lg:gap-4">
      {targetCascade.map((t, i) => (
        <CascadeTile key={t.label} t={t} previousPct={i > 0 ? targetCascade[i - 1].pct : undefined} />
      ))}
    </section>
  );
}

// ───────────── CascadeTile ─────────────

const STATUS_TONE: Record<CascadeStatus, { chip: string; ring: string }> = {
  "On Track":        { chip: "bg-emerald-50 text-emerald-700 border-emerald-200", ring: "#10b981" },
  "Slightly Behind": { chip: "bg-amber-50   text-amber-700   border-amber-200",   ring: "#f59e0b" },
  "Critical":        { chip: "bg-rose-50    text-rose-700    border-rose-200",    ring: "#ef4444" },
};

const INDEX_TONE: Record<CascadeStatus, string> = {
  "On Track":        "bg-emerald-500",
  "Slightly Behind": "bg-amber-500",
  "Critical":        "bg-rose-500",
};

const PACE_COLOR: Record<CascadeTone, string> = {
  good:  "text-emerald-700",
  watch: "text-amber-700",
  warn:  "text-rose-700",
};

function CascadeTile({
  t,
  previousPct,
}: {
  t: TargetCascadeTile;
  previousPct?: number;
}) {
  const tone = STATUS_TONE[t.status];
  const positive = t.paceTone === "good";
  const PaceIcon = positive ? ArrowUpRight : ArrowDownRight;
  void previousPct;
  return (
    <article className="card p-3.5 lg:p-5 relative overflow-hidden">
      {/* Subtle accent bar tied to the tier's status. */}
      <span
        aria-hidden
        className={cn(
          "absolute inset-x-0 top-0 h-[3px]",
          t.status === "On Track"        ? "bg-emerald-500"
          : t.status === "Slightly Behind" ? "bg-amber-500"
          : "bg-rose-500",
        )}
      />

      <header className="flex items-center gap-2 mb-3">
        <span className={cn("w-6 h-6 rounded-full text-white text-[11px] font-extrabold grid place-items-center shrink-0 shadow-sm", INDEX_TONE[t.status])}>
          {t.index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.12em] muted font-bold leading-tight">
            {t.label}
          </div>
        </div>
      </header>

      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[22px] lg:text-[24px] font-extrabold tabular leading-none text-slate-900 truncate">
            {t.amount}
          </div>
          <div className="text-[12px] muted font-semibold mt-1">
            / {t.total}
          </div>
        </div>
        <div className="shrink-0 relative">
          <ProgressRing
            pct={t.pct}
            size={64}
            stroke={6}
            color={tone.ring}
            label={`${t.pct}%`}
            animate={false}
          />
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 text-[11.5px] font-extrabold tabular",
            PACE_COLOR[t.paceTone],
          )}
        >
          <PaceIcon size={11} />
          {t.paceLabel}
        </span>
        <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold border", tone.chip)}>
          {t.status}
        </span>
      </div>

      <div className="text-caption muted font-semibold mt-1.5 truncate">
        {t.detail}
      </div>
    </article>
  );
}
