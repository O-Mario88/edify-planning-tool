"use client";

import { AlertTriangle, AlertCircle } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  priorityProjectIssues,
  type PriorityProjectIssueBadge,
} from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

const badgeTone: Record<PriorityProjectIssueBadge, string> = {
  "Low Teacher Impact": "bg-amber-100 text-amber-800",
  "Low Enrollment":     "bg-orange-100 text-[#9a3412]",
  Delayed:              "bg-red-100 text-red-700",
  "Overdue Milestone":  "bg-red-100 text-red-700",
  "Budget Risk":        "bg-[#fde68a] text-amber-800",
};

const iconTone: Record<PriorityProjectIssueBadge, string> = {
  "Low Teacher Impact": "text-[var(--color-edify-orange)]",
  "Low Enrollment":     "text-[var(--color-edify-orange)]",
  Delayed:              "text-[var(--color-danger)]",
  "Overdue Milestone":  "text-[var(--color-danger)]",
  "Budget Risk":        "text-[var(--color-edify-orange)]",
};

export function PriorityProjectsPanel() {
  return (
    <SectionCard
      icon={<AlertTriangle size={13} />}
      title="Priority Projects / Needs Attention"
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#priority">
          View All
        </a>
      }
    >
      <div className="grid grid-cols-[36px_1fr_180px_92px] gap-x-2 text-[11px] muted font-semibold uppercase tracking-wide pb-2 border-b border-[#eef2f4]">
        <div />
        <div>Issue</div>
        <div className="text-center">Status</div>
        <div className="text-right">Last Updated</div>
      </div>

      <div className="divide-y divide-[var(--color-edify-divider)]">
        {priorityProjectIssues.map((p) => (
          <div
            key={p.id}
            className="grid grid-cols-[36px_1fr_180px_92px] gap-x-2 items-center py-2.5"
          >
            <AlertCircle size={16} className={cn("shrink-0", iconTone[p.badge])} />

            <div className="min-w-0">
              <div className="text-body font-bold leading-tight truncate">
                {p.projectShortName}
              </div>
              <div className="text-[11px] muted leading-tight mt-0.5">{p.issue}</div>
            </div>

            <div className="text-center">
              <span
                className={cn(
                  "inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-bold whitespace-nowrap",
                  badgeTone[p.badge],
                )}
              >
                {p.badge}
              </span>
            </div>

            <div className="text-[11px] muted text-right tabular whitespace-nowrap">
              {p.lastUpdated}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted leading-snug flex items-start gap-1.5">
        <AlertTriangle size={11} className="text-[var(--color-edify-orange)] mt-0.5 shrink-0" />
        Priorities are ranked by special-project risk only — separate from SSA-based school priority.
      </div>
    </SectionCard>
  );
}
