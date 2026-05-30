"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  getPlanningAvailability,
  isoDate,
  isInRange,
  publicHolidays,
  conferenceWeeks,
  leaveRequests,
  type Availability,
} from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

type View = "Month" | "Week" | "List";

// 6×7 grid of dates that includes the current month plus leading/trailing
// days from neighboring months for visual continuity.
function buildMonthGrid(year: number, month0: number) {
  const first = new Date(year, month0, 1);
  const start = new Date(first);
  start.setDate(start.getDate() - start.getDay()); // back to Sunday
  const cells: { date: Date; inMonth: boolean; iso: string }[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    cells.push({ date: d, inMonth: d.getMonth() === month0, iso: isoDate(d) });
  }
  return cells;
}

function dayBlockSummary(iso: string, availability: Availability) {
  // For visual fidelity to the screenshot we surface:
  //   • Holiday chip on the holiday day
  //   • Leave chip on individual leave days
  //   • Conference chip across the conference-week range
  //   • Lock icon for any blocked day with no chip (Sundays)
  if (publicHolidays.some((h) => h.date === iso)) {
    return { chip: { label: "Holiday", color: "bg-rose-100 text-rose-700" } };
  }
  if (conferenceWeeks.some((c) => isInRange(iso, c.startDate, c.endDate))) {
    return { chip: { label: "Conference", color: "bg-violet-100 text-violet-700" } };
  }
  if (
    leaveRequests.some(
      (l) => l.approvalStatus === "Approved" && l.validLeaveDates.includes(iso),
    )
  ) {
    return { chip: { label: "Leave", color: "bg-teal-100 text-teal-700" } };
  }
  if (!availability.available) return { lock: true };
  return {};
}

export function PlanningCalendar({
  initialYear = 2025,
  initialMonth0 = 6, // July
}: {
  initialYear?: number;
  initialMonth0?: number;
}) {
  const [year, setYear] = useState(initialYear);
  const [month0, setMonth0] = useState(initialMonth0);
  const [view, setView] = useState<View>("Month");

  const cells = buildMonthGrid(year, month0);
  const monthLabel = new Date(year, month0, 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });

  function shift(dir: -1 | 1) {
    const d = new Date(year, month0 + dir, 1);
    setYear(d.getFullYear());
    setMonth0(d.getMonth());
  }
  function jumpToday() {
    setYear(initialYear);
    setMonth0(initialMonth0);
  }

  // Pre-compute availability per cell so blocked days render lock + dim
  // styling. This is the single source of truth — same call used by the
  // Planning Tool's date pickers.
  return (
    <SectionCard
      title={monthLabel}
      actions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={jumpToday}
            className="h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold"
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => shift(-1)}
            aria-label="Previous month"
            className="h-8 w-8 rounded-md border border-[var(--color-edify-border)] bg-white grid place-items-center"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            onClick={() => shift(1)}
            aria-label="Next month"
            className="h-8 w-8 rounded-md border border-[var(--color-edify-border)] bg-white grid place-items-center"
          >
            <ChevronRight size={14} />
          </button>
          <div className="ml-2 inline-flex items-center rounded-md border border-[var(--color-edify-border)] bg-white p-0.5 text-[12px] font-semibold">
            {(["Month", "Week", "List"] as View[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={cn(
                  "px-2.5 h-7 rounded",
                  view === v
                    ? "bg-[var(--color-edify-primary)] text-white"
                    : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]",
                )}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      }
    >
      {/* Day-of-week header */}
      <div className="grid grid-cols-7 text-[11px] muted font-semibold uppercase tracking-wide pb-2 border-b border-[#eef2f4]">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div key={d} className="px-2">
            {d}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div className="grid grid-cols-7 border-l border-t border-[#eef2f4] mt-2">
        {cells.map((c) => {
          const availability = getPlanningAvailability({
            date: c.iso,
            staffId: "STF-SK-001", // demo: render Sarah's leave shading
          });
          const summary = dayBlockSummary(c.iso, availability);
          const isToday = c.iso === isoDate(new Date(year, month0, new Date().getDate()));
          const blocked = !availability.available;
          const isConf = summary.chip?.label === "Conference";
          return (
            <div
              key={c.iso}
              className={cn(
                "min-h-[64px] border-r border-b border-[#eef2f4] p-1.5 relative",
                !c.inMonth && "bg-[#fafbfc]",
                isConf && "bg-violet-50/60",
                summary.chip?.label === "Leave" && "bg-teal-50/60",
                summary.chip?.label === "Holiday" && "bg-rose-50/40",
                blocked && !summary.chip && "bg-[#f4f6f8]",
              )}
            >
              <div
                className={cn(
                  "text-[12px] font-bold tabular leading-none",
                  !c.inMonth ? "text-[#cbd5d8]" : "text-[var(--color-edify-text)]",
                  isToday && "text-[var(--color-edify-primary)]",
                )}
              >
                {c.date.getDate()}
              </div>
              {summary.chip && (
                <div
                  className={cn(
                    "mt-1 inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-bold",
                    summary.chip.color,
                  )}
                >
                  {summary.chip.label}
                </div>
              )}
              {summary.lock && (
                <Lock
                  size={11}
                  className="absolute right-1.5 bottom-1.5 text-[var(--color-edify-muted)]"
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] muted">
        <LegendItem swatch="border border-[var(--color-edify-border)] bg-white" label="Available" />
        <LegendItem swatch="bg-teal-100 border border-teal-200" label="Leave" />
        <LegendItem swatch="bg-rose-100 border border-rose-200" label="Holiday" />
        <LegendItem swatch="bg-violet-100 border border-violet-200" label="Conference" />
        <span className="inline-flex items-center gap-1.5">
          <Lock size={10} className="text-[var(--color-edify-muted)]" />
          Blocked (No Planning)
        </span>
      </div>
    </SectionCard>
  );
}

function LegendItem({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("w-3 h-3 rounded", swatch)} />
      {label}
    </span>
  );
}
