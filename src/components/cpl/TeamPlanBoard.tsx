"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ArrowUpRight, Users } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type {
  TeamPlanRow,
  TeamPlanStatus,
  TeamPlanSummary,
} from "@/lib/cpl/team-plan-engine";
import { cn } from "@/lib/utils";

// Team Plan board — one expandable card per supervised CCEO, so the PL
// reads team execution without opening every CCEO page. Collapsed rows
// carry the at-a-glance read (status label, achievement, gap chips);
// expanding shows the why (status reasons, category pacing, portfolio
// gaps, blockers, recommended support actions).

const STATUS_TONE: Record<TeamPlanStatus, string> = {
  "On Track":           "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Needs Attention":    "bg-amber-50 text-amber-700 border-amber-200",
  "Behind Target":      "bg-rose-50 text-rose-700 border-rose-200",
  "Overloaded":         "bg-violet-50 text-violet-700 border-violet-200",
  "Data Quality Issue": "bg-sky-50 text-sky-700 border-sky-200",
};

function ProgressBar({ label, pct }: { label: string; pct: number }) {
  const tone = pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-400" : "bg-rose-500";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] muted font-semibold">{label}</span>
        <span className="text-[11px] font-extrabold tabular">{pct}%</span>
      </div>
      <div className="mt-0.5 h-1.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

function GapChip({ label, count, alert }: { label: string; count: number; alert?: boolean }) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold",
        alert
          ? "bg-rose-50 text-rose-700 border-rose-200"
          : "bg-[var(--color-edify-soft)]/60 border-[var(--color-edify-border)]",
      )}
    >
      {count} {label}
    </span>
  );
}

function CceoRow({ row }: { row: TeamPlanRow }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 py-2.5 px-1 text-left hover:bg-[var(--color-edify-soft)]/30 rounded-lg"
        aria-expanded={open}
      >
        <span className="grid place-items-center h-8 w-8 rounded-full bg-[var(--color-edify-soft)] text-[11px] font-extrabold shrink-0">
          {row.initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-extrabold tracking-tight truncate">{row.name}</span>
            <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-extrabold", STATUS_TONE[row.status])}>
              {row.status}
            </span>
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] muted">
            <span>{row.region}</span>
            <span>· {row.completedThisMonth}/{row.monthlyTarget} this month</span>
            <GapChip label="missing SSA" count={row.portfolio.missingSsa} alert />
            <GapChip label="unclustered" count={row.portfolio.unclustered} />
            <GapChip label="SF issues" count={row.unresolvedSalesforceIssues} alert={row.unresolvedSalesforceIssues >= 3} />
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[14px] font-extrabold tabular">{row.achievementPercent}%</span>
          <span className="block text-[10px] muted">achievement</span>
        </span>
        <ChevronDown
          size={14}
          className={cn("shrink-0 muted transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="pb-3 pl-12 pr-2 space-y-3">
          <ul className="space-y-0.5">
            {row.statusReasons.map((r) => (
              <li key={r} className="text-[12px] leading-snug flex gap-1.5">
                <span className="muted">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-4 gap-y-2">
            <ProgressBar label="Visits" pct={row.categories.visits} />
            <ProgressBar label="Trainings" pct={row.categories.trainings} />
            <ProgressBar label="SSA" pct={row.categories.ssa} />
            <ProgressBar label="Salesforce" pct={row.categories.salesforce} />
            <ProgressBar label="Core package" pct={row.categories.corePackage} />
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
            <span><strong>{row.portfolio.total}</strong> schools ({row.portfolio.core} core · {row.portfolio.client} client)</span>
            <span><strong>{row.portfolio.partnerAssigned}</strong> with partner delegation</span>
            <span><strong>{row.remainingThisMonth}</strong> activities remaining · needs <strong>{row.weeklyPaceNeeded}/week</strong></span>
          </div>

          {(row.fundingDelayDays > 0 || row.blockedPlanningDays > 0 || row.approvedLeaveDays > 0 || row.partnerDependencyBlocks > 0) && (
            <p className="text-[11.5px] muted leading-snug">
              Context before escalating:{" "}
              {[
                row.fundingDelayDays > 0 && `funds delayed ${row.fundingDelayDays}d`,
                row.blockedPlanningDays > 0 && `${row.blockedPlanningDays} blocked planning days`,
                row.approvedLeaveDays > 0 && `${row.approvedLeaveDays} approved leave days`,
                row.partnerDependencyBlocks > 0 && `${row.partnerDependencyBlocks} partner dependency blocks`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}

          {row.recommendedSupportActions.length > 0 && (
            <p className="text-[12px] leading-snug">
              <span className="font-bold">Recommended support:</span>{" "}
              {row.recommendedSupportActions.join("; ")}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Link
              href="/team-targets"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-edify-border)] px-2.5 py-1 text-[11.5px] font-bold hover:bg-[var(--color-edify-soft)]/40"
            >
              View targets <ArrowUpRight size={11} />
            </Link>
            <Link
              href={`/staff/${row.staffId}`}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--color-edify-border)] px-2.5 py-1 text-[11.5px] font-bold hover:bg-[var(--color-edify-soft)]/40"
            >
              360° profile <ArrowUpRight size={11} />
            </Link>
          </div>
        </div>
      )}
    </li>
  );
}

export function TeamPlanBoard({
  rows,
  summary,
  showSummary = true,
}: {
  rows: TeamPlanRow[];
  summary: TeamPlanSummary;
  showSummary?: boolean;
}) {
  const metrics: MetricCell[] = [
    { key: "cceos",   label: "CCEOs supervised",  value: summary.cceos },
    { key: "ontrack", label: "On track",          value: summary.byStatus["On Track"], tone: "good" },
    { key: "behind",  label: "Behind target",     value: summary.byStatus["Behind Target"], tone: summary.byStatus["Behind Target"] ? "alert" : "default" },
    { key: "over",    label: "Overloaded",        value: summary.byStatus["Overloaded"], tone: summary.byStatus["Overloaded"] ? "alert" : "default" },
    { key: "dq",      label: "Data quality",      value: summary.byStatus["Data Quality Issue"] },
    { key: "ssa",     label: "Schools missing SSA", value: summary.schoolsMissingSsa, tone: summary.schoolsMissingSsa ? "alert" : "default" },
    { key: "uncl",    label: "Unclustered",       value: summary.schoolsUnclustered },
    { key: "rem",     label: "Activities remaining", value: summary.totalRemainingThisMonth },
  ];

  return (
    <SectionCard
      icon={<Users size={13} />}
      title="Team Plan — per-CCEO execution"
      actions={
        <Link href="/team-plan" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Open Team Plan <ArrowUpRight size={12} />
        </Link>
      }
    >
      {showSummary && (
        <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-4 xl:grid-cols-8" />
      )}
      {rows.length === 0 ? (
        <p className="text-[12.5px] muted py-2">No supervised CCEOs with an active target profile.</p>
      ) : (
        <ul className={cn("divide-y divide-[var(--color-edify-divider)]", showSummary && "mt-2")}>
          {rows.map((r) => (
            <CceoRow key={r.staffId} row={r} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
