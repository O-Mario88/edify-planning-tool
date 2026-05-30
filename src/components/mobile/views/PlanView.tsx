"use client";

import { useState } from "react";
import {
  ChevronDown,
  Circle,
  CheckCircle2,
  ChevronRight,
  Database,
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
import { SalesforceCompletionModal } from "@/components/my-targets/SalesforceCompletionModal";
import type { VisitCompletion } from "@/lib/cceo-execution-store";
import { requiresParticipantCounts } from "@/lib/salesforce-id";
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
  const [active, setActive] = useState<PlanItem | null>(null);
  const [completed, setCompleted] = useState<Record<string, VisitCompletion>>({});
  const [toast, setToast] = useState<string | null>(null);
  const visible = planItems.filter((i) =>
    filter === "all" ? true : i.filter === filter,
  );

  function handleComplete(c: VisitCompletion) {
    setCompleted((prev) => ({ ...prev, [c.activityId]: c }));
    setToast(`${c.salesforceIdKind} ${c.salesforceId} logged. Submitted for verification.`);
    setTimeout(() => setToast(null), 4000);
  }

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
            visible.map((p) => (
              <PlanRow
                key={p.id}
                item={p}
                completion={completed[p.id]}
                onComplete={() => setActive(p)}
              />
            ))
          )}
        </div>
      </main>

      {active && (
        <SalesforceCompletionModal
          activity={{
            id:           active.id,
            schoolName:   active.title,
            activityType: active.type,
            purpose:      active.context,
          }}
          open
          onClose={() => setActive(null)}
          onComplete={handleComplete}
        />
      )}

      {toast && (
        <div className="fixed bottom-20 inset-x-3 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 text-center">
          {toast}
        </div>
      )}

      <MobileBottomNav />
    </MobileShell>
  );
}

function PlanRow({
  item,
  completion,
  onComplete,
}: {
  item:       PlanItem;
  completion?: VisitCompletion;
  onComplete: () => void;
}) {
  const done = !!completion;
  // The SF-ID gate is the staff completion moment: a visit/training that's
  // started ("In Progress") or already flagged "Awaiting SF ID" can be
  // closed by capturing the Salesforce ID. Verified work is already done.
  const completable = !done && (item.status === "In Progress" || item.status === "Awaiting SF ID");
  const isTraining = requiresParticipantCounts(item.type);

  return (
    <div className="px-3 py-2.5 active:bg-[var(--color-edify-soft)]/40">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "w-5 h-5 rounded-full border-2 grid place-items-center shrink-0",
            done ? "bg-emerald-500 border-emerald-500 text-white" : STATUS_RADIO[item.status],
          )}
        >
          {done || item.status === "Verified" ? <CheckCircle2 size={12} /> : <Circle size={6} className="opacity-0" />}
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
            done ? "bg-violet-50 text-violet-700" : STATUS_PILL[item.status],
          )}
        >
          {done ? "Awaiting verify" : item.status}
        </span>
        <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
      </div>

      {completion ? (
        <div className="mt-2 ml-8 rounded-lg bg-emerald-50/80 border border-emerald-200 px-2.5 py-1.5 text-[11px] text-emerald-900 leading-snug">
          <span className="font-extrabold">{completion.salesforceIdKind}:</span>{" "}
          <span className="font-mono font-extrabold">{completion.salesforceId}</span>
          {completion.participants && (
            <> · {completion.participants.total} participants</>
          )}
          <> · submitted for verification</>
        </div>
      ) : completable ? (
        <div className="mt-2 ml-8">
          <button
            type="button"
            onClick={onComplete}
            className="h-8 px-3 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-extrabold inline-flex items-center gap-1.5"
          >
            <Database size={11} />
            {isTraining ? "Complete Training · log SF ID" : "Complete Visit · log SF ID"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
