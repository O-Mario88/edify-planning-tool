"use client";

import {
  Target,
  CalendarDays,
  CalendarRange,
  Users,
  AlertTriangle,
  Building2,
  Cloud,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { teamTargetKpis, type TeamTargetKpi } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const ICON: Record<TeamTargetKpi["icon"], LucideIcon> = {
  target:        Target,
  calendar:      CalendarDays,
  calendarRange: CalendarRange,
  users:         Users,
  alertTriangle: AlertTriangle,
  school:        Building2,
  cloud:         Cloud,
};

const TONE: Record<TeamTargetKpi["tone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  emerald: "bg-[#d1fae5] text-[#065f46]",
  amber:   "bg-amber-100 text-amber-800",
  rose:    "bg-rose-100 text-rose-700",
  violet:  "bg-violet-100 text-violet-700",
};

export function TeamTargetKpiRow() {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3">
      {teamTargetKpis.map((k) => {
        const Icon = ICON[k.icon];
        const TrendIcon = k.trend.tone === "up" ? ArrowUpRight : ArrowDownRight;
        const trendCls =
          k.trend.tone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
        return (
          <div key={k.key} className="card p-3 overflow-hidden">
            <div className="flex items-start gap-2">
              <span className={cn("w-9 h-9 rounded-full grid place-items-center shrink-0", TONE[k.tone])}>
                <Icon size={15} />
              </span>
              <div className="min-w-0 flex-1 text-caption muted font-semibold leading-tight line-clamp-2">
                {k.label}
              </div>
            </div>
            <div className="text-[20px] font-extrabold tabular leading-none mt-2 truncate">{k.value}</div>
            <div className={cn("text-caption font-semibold mt-1 flex items-center gap-1 truncate", trendCls)}>
              <TrendIcon size={10} className="shrink-0" />
              <span className="truncate">{k.trend.delta}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}
