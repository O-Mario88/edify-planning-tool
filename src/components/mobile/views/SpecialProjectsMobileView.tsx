"use client";

import { Sparkles, Target, Wallet, Activity } from "lucide-react";
import {
  MobileSubpageShell,
  MobileKpiGrid,
  MobileSectionCard,
  type MobileKpiTile,
  type KpiTone,
} from "@/components/mobile/views/MobileSubpageShell";
import {
  specialProjects,
  type ProjectStatus,
} from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<ProjectStatus, KpiTone> = {
  "Draft":                 "blue",
  "Active":                "green",
  "School Selection Open": "blue",
  "Training Planned":      "blue",
  "Follow-Up Active":      "blue",
  "Monitoring":            "amber",
  "Completed":             "violet",
  "Paused":                "amber",
  "Closed":                "violet",
};

function utilizationTone(pct: number): KpiTone {
  if (pct >= 80) return "green";
  if (pct >= 50) return "amber";
  return "rose";
}

export function SpecialProjectsMobileView() {
  const totals = {
    projects:    specialProjects.length,
    active:      specialProjects.filter((p) => p.status === "Active").length,
    schools:     specialProjects.reduce((a, p) => a + (p.schoolsEnrolled ?? 0), 0),
    allocation:  specialProjects.reduce((a, p) => a + (p.totalAllocation ?? 0), 0),
  };

  const tiles: MobileKpiTile[] = [
    { key: "projects",  Icon: Sparkles, label: "Projects",     value: totals.projects.toString(),    caption: `${totals.active} active`,         tone: "violet" },
    { key: "schools",   Icon: Target,   label: "Schools Enrolled", value: totals.schools.toString(), caption: "across portfolio",                tone: "edify"  },
    { key: "alloc",     Icon: Wallet,   label: "Total Allocation", value: `UGX ${(totals.allocation / 1_000_000_000).toFixed(2)}B`, caption: "committed", tone: "amber" },
    { key: "health",    Icon: Activity, label: "Avg Health",   value: (specialProjects.reduce((a, p) => a + p.healthScore, 0) / Math.max(1, specialProjects.length)).toFixed(1), caption: "/ 5", tone: "green" },
  ];

  return (
    <MobileSubpageShell
      title="Special Projects"
      subtitle={`${totals.active} active · ${totals.projects} total in the portfolio`}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard title="Portfolio" subtitle="Status, partners, and budget health">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {specialProjects.map((p) => (
            <li key={p.projectId} className="px-3 py-3 flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight leading-tight">
                    {p.projectName}
                  </div>
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0",
                    STATUS_TONE[p.status] === "green"  ? "bg-emerald-100 text-emerald-700" :
                    STATUS_TONE[p.status] === "blue"   ? "bg-sky-100     text-sky-700"     :
                    STATUS_TONE[p.status] === "amber"  ? "bg-amber-100   text-amber-700"   :
                    STATUS_TONE[p.status] === "violet" ? "bg-violet-100  text-violet-700"  :
                                                          "bg-slate-100   text-slate-700"  ,
                  )}>
                    {p.status}
                  </span>
                </div>
                <div className="text-caption muted truncate">
                  {p.projectType} · {p.assignedPartnerName ?? "No partner"}
                </div>
                <div className="text-caption muted truncate">
                  {p.schoolsEnrolled ?? 0}/{p.targetNumber} {p.impactMeasurementType.toLowerCase()} ·
                  {p.teachersImpacted ? ` ${p.teachersImpacted} teachers` : ""}
                </div>
                {p.budgetUtilizationPct !== undefined && (
                  <div className="mt-1 flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(100, p.budgetUtilizationPct)}%`,
                          backgroundColor:
                            utilizationTone(p.budgetUtilizationPct) === "green" ? "#10b981" :
                            utilizationTone(p.budgetUtilizationPct) === "amber" ? "#f59e0b" :
                                                                                   "#ef4444",
                        }}
                      />
                    </div>
                    <span className="text-caption font-extrabold tabular shrink-0">
                      {p.budgetUtilizationPct}% used
                    </span>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}
