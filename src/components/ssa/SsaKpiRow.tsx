"use client";

import {
  Building2,
  CheckCircle2,
  Users,
  Star,
  AlertTriangle,
  Building,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import { ssaKpis, type SsaKpi } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<SsaKpi["icon"], LucideIcon> = {
  school:        Building2,
  checkCircle:   CheckCircle2,
  users:         Users,
  star:          Star,
  alertTriangle: AlertTriangle,
  building:      Building,
};

const tile: Record<SsaKpi["iconTone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  emerald: "bg-[#d1fae5] text-[#065f46]",
  amber:   "bg-amber-100 text-amber-800",
  rose:    "bg-rose-100 text-rose-700",
  violet:  "bg-violet-100 text-violet-700",
};

export function SsaKpiRow() {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
      {ssaKpis.map((k) => {
        const Icon = iconMap[k.icon];
        return (
          <div key={k.key} className="card p-3 overflow-hidden">
            <div className="flex items-start gap-2.5">
              <span
                className={cn(
                  "w-10 h-10 rounded-full grid place-items-center shrink-0",
                  tile[k.iconTone],
                )}
              >
                <Icon size={16} />
              </span>
              <div className="leading-tight min-w-0 flex-1">
                <div className="text-[11px] muted font-semibold leading-tight line-clamp-2 min-h-[28px]">
                  {k.label}
                </div>
                <div className="flex items-baseline gap-1 mt-1.5 truncate">
                  <span className="text-[22px] font-extrabold tabular leading-none">{k.value}</span>
                  {k.unit && (
                    <span className="text-[11px] muted font-semibold truncate">{k.unit}</span>
                  )}
                </div>
              </div>
            </div>
            {(k.caption || k.trend) && (
              <div className="mt-2 flex items-center gap-1 text-caption truncate min-w-0">
                {k.trend && (
                  <span className="inline-flex items-center gap-1 text-[var(--color-success)] font-semibold shrink-0">
                    <ArrowUpRight size={10} />
                    {k.trend.delta}
                  </span>
                )}
                {k.caption && <span className="muted truncate">{k.caption}</span>}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
