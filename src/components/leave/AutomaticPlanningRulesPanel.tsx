"use client";

import {
  CalendarDays,
  CalendarHeart,
  Users,
  Lock,
  Sparkles,
  Flag,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  planningRules,
  canEditPlanningRule,
  type PlanningRule,
} from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<PlanningRule["icon"], LucideIcon> = {
  calendarDays:  CalendarDays,
  calendarHeart: CalendarHeart,
  users:         Users,
  lock:          Lock,
  sparkles:      Sparkles,
  flag:          Flag,
};

const tile: Record<PlanningRule["tone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  rose:    "bg-rose-100 text-rose-700",
  violet:  "bg-violet-100 text-violet-700",
  slate:   "bg-[#e2e8f0] text-[#334155]",
  emerald: "bg-[#d1fae5] text-[#065f46]",
  amber:   "bg-amber-100 text-amber-800",
};

export function AutomaticPlanningRulesPanel({
  role = "CCEO" as const,
}: {
  role?: "CCEO" | "CountryProgramLead" | "CountryDirector" | "Admin";
}) {
  return (
    <SectionCard title="Automatic Planning Rules">
      <div className="space-y-2">
        {planningRules.map((r) => {
          const Icon = iconMap[r.icon];
          const editable = canEditPlanningRule(role, r);
          return (
            <div
              key={r.key}
              className="flex items-center gap-3 px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)]"
            >
              <span className={cn("w-9 h-9 rounded-md grid place-items-center shrink-0", tile[r.tone])}>
                <Icon size={15} />
              </span>
              <div className="flex-1 text-body font-semibold leading-tight">{r.label}</div>
              <span className="text-[11px] font-bold text-[var(--color-success)]">
                {editable ? "Enabled" : "Locked"}
              </span>
              <Toggle on={r.enabled} disabled={!editable} />
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-start gap-2 text-[11px]">
        <ShieldCheck size={12} className="text-[var(--color-success)] mt-0.5 shrink-0" />
        <span className="muted leading-snug">
          All rules are active and enforced by the planning engine.
        </span>
      </div>
    </SectionCard>
  );
}

function Toggle({ on, disabled }: { on: boolean; disabled?: boolean }) {
  return (
    <span
      className={cn(
        "relative inline-block w-9 h-5 rounded-full transition-colors",
        on ? "bg-[var(--color-success)]" : "bg-[#e2e8f0]",
        disabled && "opacity-70 cursor-not-allowed",
      )}
      aria-checked={on}
      role="switch"
    >
      <span
        className={cn(
          "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
          on ? "translate-x-[18px]" : "translate-x-0.5",
        )}
      />
    </span>
  );
}
