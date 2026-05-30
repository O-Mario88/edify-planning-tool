"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

// Mini month grid for May 2026. Cells colored by daily pacing.
type Cell = { day: number; tone: "track" | "slight" | "behind" | "neutral" | "today" };

const cells: (Cell | null)[] = (() => {
  const days: (Cell | null)[] = [];
  // 4 leading blanks (May 1 2026 = Friday in calendar; for simplicity start on Sun of week 1)
  for (let i = 0; i < 4; i++) days.push({ day: 28 + i, tone: "neutral" });
  for (let d = 1; d <= 31; d++) {
    const tone: Cell["tone"] =
      d === 12 ? "today" :
      d % 7 === 0 ? "behind" :
      d % 5 === 0 ? "slight" :
      "track";
    days.push({ day: d, tone });
  }
  while (days.length < 42) days.push(null);
  return days;
})();

const TONE: Record<Cell["tone"], string> = {
  track:   "bg-emerald-50 text-emerald-700",
  slight:  "bg-amber-50 text-amber-700",
  behind:  "bg-rose-50 text-rose-700",
  neutral: "bg-white text-[var(--color-edify-muted)]",
  today:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]",
};

export function MiniMonthlyCalendar() {
  return (
    <SectionCard
      title="May 2026"
      actions={
        <div className="flex items-center gap-1">
          <button type="button" aria-label="Previous month" className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] bg-white grid place-items-center">
            <ChevronLeft size={12} />
          </button>
          <button type="button" aria-label="Next month" className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] bg-white grid place-items-center">
            <ChevronRight size={12} />
          </button>
        </div>
      }
    >
      <div className="grid grid-cols-7 text-[10px] muted font-semibold uppercase pb-1.5 border-b border-[#eef2f4]">
        {["Mo","Tu","We","Th","Fr","Sa","Su"].map((d) => (
          <div key={d} className="text-center">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1 mt-2">
        {cells.map((c, i) =>
          c === null ? (
            <div key={i} className="h-7" />
          ) : (
            <div
              key={i}
              className={cn(
                "h-7 rounded-md grid place-items-center text-[11px] font-bold tabular",
                TONE[c.tone],
              )}
            >
              {c.day}
            </div>
          ),
        )}
      </div>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center gap-3 text-caption muted">
        <Legend swatch="bg-emerald-200" label="On track" />
        <Legend swatch="bg-amber-200" label="Slightly behind" />
        <Legend swatch="bg-rose-200" label="Behind" />
      </div>
    </SectionCard>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-2.5 h-2.5 rounded ${swatch}`} />
      {label}
    </span>
  );
}
