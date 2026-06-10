"use client";

import { Clock, MapPin, CalendarDays, Calendar } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { projectMilestones, type Milestone } from "@/lib/special-projects-mock";
import {
  isFilterActive,
  useActiveFilters,
  useResolvedDateRange,
} from "@/hooks/use-active-filters";
import { applyDateScope } from "@/lib/filters/apply-filters";

const monthAccent: Record<string, string> = {
  MAY: "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]",
  JUN: "border-[var(--color-edify-orange)] text-[var(--color-edify-orange)]",
};

function dateBlock(iso: string): { mon: string; day: string } {
  const d = new Date(iso + "T00:00:00");
  return {
    mon: d.toLocaleDateString("en-US", { month: "short" }).toUpperCase(),
    day: d.toLocaleDateString("en-US", { day: "2-digit" }),
  };
}

export function UpcomingMilestonesCalendar() {
  // Header filters → data. Milestones carry an ISO date, so the FY/Quarter
  // window applies; no scoping when no FY/Quarter is selected (the mock
  // calendar spans periods). Geography is skipped — `location` is free text
  // ("Virtual", "All Regions", office names), not a district field.
  const selection = useActiveFilters();
  const range = useResolvedDateRange();
  const periodActive =
    isFilterActive(selection.fy) || isFilterActive(selection.quarter);
  const milestones = periodActive
    ? applyDateScope(projectMilestones, range, (m) => m.date)
    : projectMilestones;

  return (
    <SectionCard
      icon={<Calendar size={13} />}
      title="Upcoming Milestones / Project Calendar"
      actions={
        <button
          type="button"
          className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold flex items-center gap-1.5"
        >
          <CalendarDays size={13} className="text-[var(--color-edify-primary)]" />
          View Calendar
        </button>
      }
    >
      {milestones.length === 0 ? (
        <div className="text-caption muted py-4 text-center">
          No milestones in the selected period.
        </div>
      ) : (
        <div className="grid grid-cols-6 gap-3">
          {milestones.map((m) => (
            <MilestoneCard key={m.id} m={m} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function MilestoneCard({ m }: { m: Milestone }) {
  const { mon, day } = dateBlock(m.date);
  const accent = monthAccent[mon] ?? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]";
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
      <div className="flex items-start gap-3">
        <div
          className={`shrink-0 w-12 rounded-lg border-2 ${accent} bg-white flex flex-col items-center justify-center py-1`}
        >
          <div className="text-[10px] font-extrabold tracking-wide">{mon}</div>
          <div className="text-[18px] font-extrabold tabular leading-none">{day}</div>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-body font-bold leading-tight">{m.title}</div>
          <div className="text-caption muted truncate">{m.projectName}</div>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-3 text-caption muted">
        <span className="inline-flex items-center gap-1">
          <Clock size={10} />
          {m.time}
        </span>
        <span className="inline-flex items-center gap-1 truncate">
          <MapPin size={10} />
          <span className="truncate">{m.location}</span>
        </span>
      </div>
    </div>
  );
}
