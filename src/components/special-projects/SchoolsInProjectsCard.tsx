"use client";

import { Building2, School } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import {
  schoolsInProjectsKpis,
  prioritySchoolsToAdd,
  type PrioritySchoolToAdd,
} from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

const priorityChip: Record<PrioritySchoolToAdd["priority"], string> = {
  "High Priority":   "bg-red-100 text-red-700",
  "Medium Priority": "bg-amber-100 text-amber-800",
};

export function SchoolsInProjectsCard() {
  return (
    <SectionCard
      icon={<School size={13} />}
      title="Schools in Projects"
    >
      <MetricStrip
        bare
        className="mb-3"
        columns="grid-cols-4"
        metrics={schoolsInProjectsKpis.map((k) => ({
          key: k.key,
          label: k.label,
          value: k.value,
          delta: { dir: k.deltaTone === "up" ? "up" : "down", text: `${k.delta} vs Apr` },
        }))}
      />

      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[12px] font-bold">Priority Schools to Add / Follow Up</div>
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#priority-schools">
          View All
        </a>
      </div>

      <div className="divide-y divide-[var(--color-edify-divider)]">
        {prioritySchoolsToAdd.map((s) => (
          <div key={s.id} className="flex items-center gap-2 py-2">
            <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
              <Building2 size={13} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-body font-semibold truncate">{s.schoolName}</div>
              <div className="text-caption muted truncate">{s.district}</div>
            </div>
            <span
              className={cn(
                "inline-flex items-center px-2 py-[2px] rounded-md text-caption font-semibold shrink-0",
                priorityChip[s.priority],
              )}
            >
              {s.priority}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-caption muted leading-snug">
        Schools may belong to multiple special projects.
      </div>
    </SectionCard>
  );
}
