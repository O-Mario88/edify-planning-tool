"use client";

import {
  CalendarCheck,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  School,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoMonthPlanner } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// The Month Planner — a 5-week × 2-activity-row matrix. Each cell is a
// count plus a dot row visualizing capacity used (max 6 dots). The
// footer carries total days planned, totals per activity, and any
// buffer days the CCEO still has uncommitted.
export function CceoMonthPlannerCard() {
  const m = cceoMonthPlanner;
  const clusterTotal   = m.columns.reduce((a, c) => a + c.clusterTrainings, 0);
  const inSchoolTotal  = m.columns.reduce((a, c) => a + c.inSchoolActivities, 0);

  return (
    <SectionCard
      icon={<CalendarCheck size={13} />}
      title="Month Planner"
      actions={
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="h-7 px-2 rounded-md bg-[var(--color-edify-soft)]/50 border border-transparent hover:border-[var(--color-edify-border)] text-[11.5px] font-semibold inline-flex items-center gap-1 text-slate-700"
          >
            {m.month}
          </button>
          <button
            type="button"
            aria-label="Previous month"
            className="h-7 w-7 rounded-md grid place-items-center hover:bg-[var(--color-edify-soft)]/50 text-slate-500"
          >
            <ChevronLeft size={13} />
          </button>
          <button
            type="button"
            aria-label="Next month"
            className="h-7 w-7 rounded-md grid place-items-center hover:bg-[var(--color-edify-soft)]/50 text-slate-500"
          >
            <ChevronRight size={13} />
          </button>
        </div>
      }
    >
      <div className="rounded-xl border border-[var(--color-edify-border)] overflow-hidden">
        {/* Week header */}
        <div className="grid grid-cols-[120px_repeat(5,1fr)] bg-[var(--color-edify-soft)]/40">
          <div />
          {m.columns.map((c) => (
            <div key={c.weekLabel} className="px-2 py-2 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wide text-slate-600">
                {c.weekLabel}
              </div>
              <div className="text-[9.5px] muted font-semibold leading-tight">
                {c.rangeLabel}
              </div>
            </div>
          ))}
        </div>

        {/* Cluster Trainings row */}
        <PlannerRow
          label="Cluster Trainings"
          icon={GraduationCap}
          iconTone="bg-violet-100 text-violet-700"
          values={m.columns.map((c) => c.clusterTrainings)}
        />

        {/* In-School Activities row */}
        <PlannerRow
          label="In-School Activities"
          icon={School}
          iconTone="bg-emerald-100 text-emerald-700"
          values={m.columns.map((c) => c.inSchoolActivities)}
        />
      </div>

      {/* Footer stats — total days planned, per-activity totals, buffer */}
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <FooterStat label="Total Days Planned" value={m.totalDaysPlanned} />
        <FooterStat label="Cluster Trainings"  value={String(clusterTotal)} />
        <FooterStat label="In-School Activities" value={String(inSchoolTotal)} />
        <FooterStat label="Buffer Days"        value={String(m.bufferDays)} tone="watch" />
      </div>
    </SectionCard>
  );
}

// ───────────── PlannerRow ─────────────

function PlannerRow({
  label,
  icon: Icon,
  iconTone,
  values,
}: {
  label: string;
  icon: typeof GraduationCap;
  iconTone: string;
  values: number[];
}) {
  return (
    <div className="grid grid-cols-[120px_repeat(5,1fr)] border-t border-[#eef2f4]">
      <div className="flex items-center gap-1.5 px-2 py-2.5 bg-white">
        <span className={cn("w-6 h-6 rounded-md grid place-items-center shrink-0", iconTone)}>
          <Icon size={11} />
        </span>
        <span className="text-caption font-semibold leading-tight text-slate-700">
          {label}
        </span>
      </div>
      {values.map((v, i) => (
        <div key={i} className="px-1.5 py-2.5 flex flex-col items-center bg-white">
          <span className="text-[18px] font-extrabold tabular leading-none text-slate-900">{v}</span>
          <DotRow count={v} />
        </div>
      ))}
    </div>
  );
}

// ───────────── DotRow — capacity visualizer ─────────────

function DotRow({ count }: { count: number }) {
  const filled = Math.min(6, count);
  const empty  = Math.max(0, 6 - filled);
  return (
    <div className="flex items-center gap-[3px] mt-1">
      {Array.from({ length: filled }).map((_, i) => (
        <span key={`f-${i}`} className="w-1 h-1 rounded-full bg-emerald-500" />
      ))}
      {Array.from({ length: empty }).map((_, i) => (
        <span key={`e-${i}`} className="w-1 h-1 rounded-full bg-slate-200" />
      ))}
    </div>
  );
}

// ───────────── FooterStat ─────────────

function FooterStat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "watch";
}) {
  return (
    <div className="rounded-lg bg-[var(--color-edify-soft)]/40 px-2.5 py-2 text-center">
      <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={cn(
        "text-[15px] font-extrabold tabular leading-none mt-0.5",
        tone === "watch" ? "text-amber-700" : "text-slate-900",
      )}>
        {value}
      </div>
    </div>
  );
}
