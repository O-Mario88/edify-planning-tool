"use client";

import {
  User,
  CalendarDays,
  CalendarHeart,
  Lock,
  RotateCw,
  Users,
  TrendingUp,
  Minus,
  type LucideIcon,
} from "lucide-react";
import { leaveKpis, type LeaveKpi } from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

// Compact 6-KPI stat row.
//
// Was a 2/3/6-column grid of large square cards that visually competed
// with the Today's-Plan hero above. The redesign keeps all 6 metrics
// (they're useful) but tightens them into a flatter, more premium
// horizontal stat bar where:
//   • the value reads first (24px tabular)
//   • the icon is small + tinted, not the focal point
//   • a trend chip lives next to the value
//   • cards sit on a single rounded surface with hairline dividers,
//     mirroring Stripe / Linear / Vercel dashboards
//
// 2 cols on phone, 3 cols on tablet, 6 cols on desktop. Equal heights
// regardless of caption length.

const iconMap: Record<LeaveKpi["icon"], LucideIcon> = {
  user:          User,
  calendarDays:  CalendarDays,
  calendarHeart: CalendarHeart,
  lock:          Lock,
  rotate:        RotateCw,
  users:         Users,
};

const tile: Record<LeaveKpi["iconTone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  amber:   "bg-amber-100   text-amber-700",
  rose:    "bg-rose-100    text-rose-700",
  slate:   "bg-slate-100   text-slate-600",
  emerald: "bg-emerald-100 text-emerald-700",
  violet:  "bg-violet-100  text-violet-700",
};

// Hand-picked trend pills per KPI key — when this hooks up to real
// data the mock returns the actual deltas; for now we render the
// direction signals that match the demo dataset.
const TREND: Record<string, { delta: string; tone: "up" | "down" | "flat" }> = {
  on_leave:        { delta: "+2",  tone: "up"   },
  approved_days:   { delta: "+8",  tone: "up"   },
  public_holidays: { delta: "—",   tone: "flat" },
  blocked_days:    { delta: "+1",  tone: "up"   },
  auto_resched:    { delta: "+6",  tone: "up"   },
  conference:      { delta: "—",   tone: "flat" },
};

export function LeaveKpiRow() {
  return (
    <section className="card rounded-2xl overflow-hidden">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {leaveKpis.map((k, i) => {
          const Icon  = iconMap[k.icon];
          const trend = TREND[k.key] ?? { delta: "—", tone: "flat" };
          // Dividers between tiles on the same row + between rows.
          const lastOnRowLg = (i + 1) % 6 === 0;
          const lastOnRowSm = (i + 1) % 3 === 0;
          const lastOnRowXs = (i + 1) % 2 === 0;
          return (
            <div
              key={k.key}
              className={cn(
                "p-4 lg:p-4 flex flex-col gap-2.5",
                // Right border on every tile except the last in each row.
                !lastOnRowXs &&  "border-r border-[var(--color-edify-divider)]",
                !lastOnRowSm &&  "sm:border-r",
                lastOnRowSm  && !lastOnRowLg && "sm:border-r-0 lg:border-r",
                !lastOnRowLg && "lg:border-r lg:border-[var(--color-edify-divider)]",
                // Bottom border on phone (rows of 2) when not on the last row.
                i < leaveKpis.length - (leaveKpis.length % 2 === 0 ? 2 : 1) && "border-b border-[var(--color-edify-divider)]",
                "sm:border-b-0",
              )}
            >
              <div className="flex items-center gap-2">
                <span className={cn("h-7 w-7 rounded-lg grid place-items-center shrink-0", tile[k.iconTone])}>
                  <Icon size={13} />
                </span>
                <div className="text-caption font-bold uppercase tracking-[0.06em] text-muted leading-tight">
                  {k.label}
                </div>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[24px] font-extrabold tabular leading-none">{k.value}</span>
                <span className="text-[11px] font-semibold text-muted">{k.unit}</span>
                <TrendChip {...trend} />
              </div>
              <div className="text-caption text-muted font-medium mt-auto truncate">{k.caption}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function TrendChip({ delta, tone }: { delta: string; tone: "up" | "down" | "flat" }) {
  const cls =
    tone === "up"
      ? "bg-emerald-50 text-emerald-700"
      : tone === "down"
        ? "bg-rose-50 text-rose-700"
        : "bg-[var(--color-edify-soft)] text-muted";
  return (
    <span className={cn("ml-auto inline-flex items-center gap-1 px-1.5 h-5 rounded-md text-[10px] font-extrabold", cls)}>
      {tone === "flat" ? <Minus size={10} /> : <TrendingUp size={10} className={tone === "down" ? "rotate-180" : undefined} />}
      {delta}
    </span>
  );
}
