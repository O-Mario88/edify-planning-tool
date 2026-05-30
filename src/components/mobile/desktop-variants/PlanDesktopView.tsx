"use client";

import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  planDataForRole,
  type PlanFilter,
} from "@/lib/mobile-mock";
import type { EdifyRole } from "@/lib/auth-public";
import { MyPlanCard } from "@/components/planning/MyPlanCard";
import { PlanScheduleByWeek } from "@/components/planning/PlanScheduleByWeek";
import { cn } from "@/lib/utils";

// Type + status visual tone maps used to live here for the flat
// activity grid. The grid is gone — PlanScheduleByWeek owns the
// activity rendering now (with its own internal tone maps that stay
// in sync across surfaces). Keep this file lean.

const FILTERS: { key: PlanFilter; label: string }[] = [
  { key: "all",        label: "All" },
  { key: "cluster",    label: "Cluster" },
  { key: "in_school",  label: "In-School" },
  { key: "follow_up",  label: "Follow-Up" },
];

export function PlanDesktopView({ role = "CountryProgramLead" }: { role?: EdifyRole }) {
  const { items: planItems } = planDataForRole(role);
  const [filter, setFilter] = useState<PlanFilter>("all");
  const visible = planItems.filter((i) => (filter === "all" ? true : i.filter === filter));
  const counts = {
    total:      planItems.length,
    inProgress: planItems.filter((p) => p.status === "In Progress").length,
    verified:   planItems.filter((p) => p.status === "Verified").length,
    awaiting:   planItems.filter((p) => p.status === "Awaiting SF ID").length,
  };

  return (
    <>
      <PageHeader
        title="My Plan"
        subtitle="Your Plan across every horizon, and the activities scheduled for the current month."
      />

      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-3">
        {/* Periodized plan — the same My Plan shown on the dashboard card. */}
        <MyPlanCard role={role === "CCEO" ? "cceo" : "cpl"} hideOpenLink />

        {/* This Month — high-level pulse on the unfiltered plan. Filter
            chips below refine the schedule but the pulse stays anchored
            to the full month so "Total / Verified / In progress" never
            shifts under the user's feet while they scope by type. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Total"       value={counts.total} />
          <Stat label="Verified"    value={counts.verified}   tone="green" />
          <Stat label="In progress" value={counts.inProgress} tone="amber" />
          <Stat label="Awaiting SF" value={counts.awaiting}   tone="rose" />
        </div>

        {/* Filter chips — refine the schedule below by activity type. */}
        <div className="card rounded-2xl p-3 flex items-center gap-1.5 flex-wrap">
          {FILTERS.map((f) => {
            const active = f.key === filter;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "h-9 px-3 rounded-full text-[12px] font-extrabold tracking-tight border whitespace-nowrap",
                  active
                    ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                    : "bg-white text-[var(--color-edify-text)] border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
                )}
              >
                {f.label}
              </button>
            );
          })}
          <Link
            href="/plans/new"
            className="ml-auto h-9 px-3.5 rounded-full inline-flex items-center gap-1.5 text-[12px] font-extrabold bg-emerald-600 text-white hover:bg-emerald-700 transition-colors"
          >
            <Plus size={13} />
            Plan a new visit
          </Link>
        </div>

        {/* Weekly schedule with fund-need rollups. This IS the activity
            list — grouped by week, sorted chronologically within each
            week, with per-week and month-total disbursements. The
            filter chips above refine which items are surfaced; the
            schedule handles its own empty state when nothing matches.
            Same view the Accountant / CD / RVP see (different framing). */}
        <PlanScheduleByWeek items={visible} audience="owner" />
      </div>
    </>
  );
}

function Stat({ label, value, tone = "edify" }: { label: string; value: number; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className={cn("rounded-xl p-3", TONE[tone])}>
      <div className="text-[10px] font-bold uppercase tracking-wide leading-tight opacity-90">{label}</div>
      <div className="text-[22px] font-extrabold tabular leading-none mt-1.5">{value}</div>
    </div>
  );
}
