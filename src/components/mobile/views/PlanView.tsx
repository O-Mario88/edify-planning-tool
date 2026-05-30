"use client";

import { useState } from "react";
import {
  ChevronDown,
  Circle,
  CheckCircle2,
  ChevronRight,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  planWeeks,
  planDataForRole,
  type PlanFilter,
  type PlanItem,
  type PlanItemStatus,
} from "@/lib/mobile-mock";
import type { EdifyRole } from "@/lib/auth-public";
import { MyPlanCard } from "@/components/planning/MyPlanCard";
import { PlanScheduleByWeek } from "@/components/planning/PlanScheduleByWeek";
import { cn } from "@/lib/utils";

const FILTERS: { key: PlanFilter; label: string }[] = [
  { key: "all",       label: "All" },
  { key: "cluster",   label: "Cluster" },
  { key: "in_school", label: "In-School" },
  { key: "follow_up", label: "Follow-Up" },
];

const STATUS_PILL: Record<PlanItemStatus, string> = {
  Planned:          "bg-blue-50 text-blue-700",
  "In Progress":    "bg-orange-50 text-orange-700",
  Verified:         "bg-emerald-50 text-emerald-700",
  "Awaiting SF ID": "bg-amber-50 text-amber-700",
};

const STATUS_RADIO: Record<PlanItemStatus, string> = {
  Planned:          "border-blue-500 text-blue-500",
  "In Progress":    "border-orange-500 text-orange-500",
  Verified:         "bg-emerald-500 border-emerald-500 text-white",
  "Awaiting SF ID": "border-amber-500 text-amber-500",
};

export function PlanView({ role = "CountryProgramLead" }: { role?: EdifyRole }) {
  const { items: planItems, summary: monthSummary } = planDataForRole(role);
  const [filter, setFilter] = useState<PlanFilter>("all");
  const visible = planItems.filter((i) =>
    filter === "all" ? true : i.filter === filter,
  );

  return (
    <MobileShell>
      <MobileTopBar backHref="/dashboard" />

      <main className="flex-1 px-3 py-3 space-y-3">
        {/* Periodized plan — the same My Plan shown on the dashboard card. */}
        <MyPlanCard role={role === "CCEO" ? "cceo" : "cpl"} hideOpenLink />

        {/* Weekly schedule with fund-need rollups. Same surface the
            Accountant / CD / RVP see; here it tells the field user
            what disbursements their plan will trigger each week.
            Starts collapsed to one week on phones to keep the page
            scannable; tap a week header to expand. */}
        <PlanScheduleByWeek items={planItems} audience="owner" initialExpanded="first" />

        {/* Month dropdown */}
        <button
          type="button"
          className="w-full h-10 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-center gap-2 text-[13px] font-bold"
        >
          May 2025
          <ChevronDown size={14} className="text-[var(--color-edify-muted)]" />
        </button>

        {/* Week selector */}
        <div className="flex gap-2 overflow-x-auto -mx-3 px-3 pb-1">
          {planWeeks.map((w) => (
            <button
              key={w.week}
              type="button"
              className={cn(
                "shrink-0 rounded-xl border px-3 py-1.5 text-center min-w-[78px] transition-colors",
                w.current
                  ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white shadow-[0_2px_8px_-2px_rgba(15,23,32,0.15)]"
                  : "bg-white border-[var(--color-edify-border)] hover:border-[var(--color-edify-primary)]/30",
              )}
            >
              <div className={cn("text-[10px] font-extrabold tracking-wider", w.current ? "text-white/85" : "muted")}>
                WEEK {w.week}
              </div>
              <div className={cn("text-[11.5px] font-bold", w.current ? "text-white" : "")}>{w.range}</div>
            </button>
          ))}
        </div>

        {/* 4 stat tiles */}
        <div className="grid grid-cols-2 gap-2">
          {monthSummary.totals.map((t) => (
            <div
              key={t.key}
              className="rounded-xl bg-white border border-[var(--color-edify-border)] p-3 text-center"
            >
              <div className="text-[20px] font-extrabold tabular leading-none">{t.value}</div>
              <div className="text-caption muted font-semibold mt-1.5 leading-tight line-clamp-2 min-h-[26px]">
                {t.label}
              </div>
            </div>
          ))}
        </div>

        {/* Month footer (Planned + Cost) */}
        <div className="grid grid-cols-2 gap-2">
          {monthSummary.monthFooters.map((f) => (
            <div
              key={f.key}
              className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 text-center"
            >
              <div className="text-[18px] font-extrabold tabular leading-none text-emerald-700">{f.value}</div>
              <div className="text-caption text-emerald-700 font-semibold mt-1.5 leading-tight line-clamp-2 min-h-[26px]">
                {f.label}
              </div>
            </div>
          ))}
        </div>

        {/* This Week Summary */}
        <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <div className="text-[12px] font-extrabold tracking-tight mb-2">
            This Week Summary <span className="muted font-medium">({monthSummary.weekStart})</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-body">
            <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5">
              <div className="text-[18px] font-extrabold tabular leading-none">{monthSummary.weekSummary.plannedActivities}</div>
              <div className="text-caption muted font-semibold mt-1">Planned Activities</div>
            </div>
            <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5">
              <div className="text-[18px] font-extrabold tabular leading-none">{monthSummary.weekSummary.totalCost}</div>
              <div className="text-caption muted font-semibold mt-1">Total Cost for Week</div>
            </div>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-1 -mx-1 px-1 overflow-x-auto">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "h-8 px-3.5 rounded-full text-[12px] font-semibold whitespace-nowrap shrink-0 transition-colors",
                  active
                    ? "bg-[var(--color-edify-primary)] text-white"
                    : "bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:border-[var(--color-edify-primary)]/30",
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* Activity list */}
        <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm divide-y divide-[var(--color-edify-divider)]">
          {visible.length === 0 ? (
            <div className="text-[12px] muted text-center py-6">No activities in this filter.</div>
          ) : (
            visible.map((p) => <PlanRow key={p.id} item={p} />)
          )}
        </div>
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}

function PlanRow({ item }: { item: PlanItem }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 active:bg-[var(--color-edify-soft)]/40">
      <span
        className={cn(
          "w-5 h-5 rounded-full border-2 grid place-items-center shrink-0",
          STATUS_RADIO[item.status],
        )}
      >
        {item.status === "Verified" ? <CheckCircle2 size={12} /> : <Circle size={6} className="opacity-0" />}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-body font-bold leading-tight">
          {item.title} <span className="muted font-medium">— {item.context}</span>
        </div>
        <div className="text-[11px] muted mt-0.5">{item.date}</div>
      </div>
      <span
        className={cn(
          "shrink-0 inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-extrabold",
          STATUS_PILL[item.status],
        )}
      >
        {item.status}
      </span>
      <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
    </div>
  );
}
