"use client";

import { Activity, Info } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { interventionScores, type InterventionRow } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const perfPill: Record<InterventionRow["performance"], string> = {
  High:   "bg-emerald-100 text-emerald-700",
  Medium: "bg-amber-100 text-amber-700",
  Low:    "bg-rose-100 text-rose-700",
};

const barColor: Record<InterventionRow["performance"], string> = {
  High:   "#16a34a",
  Medium: "#f59e0b",
  Low:    "#ef4444",
};

export function InterventionPerformanceCard() {
  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="8 Intervention Performance Overview"
      actions={<Info size={13} className="text-[var(--color-edify-muted)]" />}
    >
      <div className="grid grid-cols-[24px_2fr_1fr_88px_88px] gap-x-2 text-[11px] muted font-semibold uppercase tracking-wide pb-2 border-b border-[#eef2f4]">
        <div />
        <div>Intervention <span className="font-medium normal-case">(Score out of 10)</span></div>
        <div />
        <div className="text-right">Average Score</div>
        <div className="text-center">Performance</div>
      </div>

      <div className="divide-y divide-[var(--color-edify-divider)]">
        {interventionScores.map((r) => (
          <div
            key={r.label}
            className="grid grid-cols-[24px_2fr_1fr_88px_88px] gap-x-2 items-center py-2.5"
          >
            <div className="w-5 h-5 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-caption font-extrabold tabular">
              {r.rank}
            </div>
            <div className="text-body font-semibold truncate">{r.label}</div>
            <div className="h-2.5 rounded-full bg-[#eef2f4] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${(r.score / 10) * 100}%`, background: barColor[r.performance] }}
              />
            </div>
            <div className="text-right tabular text-body font-bold">{r.score.toFixed(2)}</div>
            <div className="text-center">
              <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold", perfPill[r.performance])}>
                {r.performance}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 text-caption muted text-center">Score (out of 10)</div>
    </SectionCard>
  );
}
