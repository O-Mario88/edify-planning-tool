"use client";

import { Building2, ArrowUpRight, ArrowDownRight, School } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
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
      <div className="grid grid-cols-4 gap-2.5 mb-3">
        {schoolsInProjectsKpis.map((k) => {
          const TrendIcon = k.deltaTone === "up" ? ArrowUpRight : ArrowDownRight;
          const trendCls =
            k.deltaTone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
          return (
            <div
              key={k.key}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 overflow-hidden"
            >
              <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">{k.label}</div>
              <div className="text-[18px] font-extrabold tabular leading-none mt-1.5 truncate">
                {k.value}
              </div>
              <div className={cn("text-[10px] font-semibold mt-1 flex items-center gap-1 truncate", trendCls)}>
                <TrendIcon size={10} className="shrink-0" />
                <span className="truncate">{k.delta} <span className="muted font-medium">vs Apr</span></span>
              </div>
            </div>
          );
        })}
      </div>

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
