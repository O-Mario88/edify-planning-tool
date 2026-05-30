"use client";

import {
  Route,
  Users,
  Calendar,
  Gauge,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  routeCapacityKpis,
  routeCceoTable,
  type RouteCapacityKpi,
  type RouteQuality,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<RouteCapacityKpi["icon"], LucideIcon> = {
  route:    Route,
  users:    Users,
  calendar: Calendar,
  gauge:    Gauge,
};

// 4-tone discipline: decorative `blue` collapses into `edify` (informational).
// Status tones reserved for amber (pending) and rose (critical).
const toneFrame: Record<RouteCapacityKpi["tone"], string> = {
  edify: "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  amber: "bg-amber-100 text-amber-800",
  rose:  "bg-rose-100 text-rose-700",
  blue:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
};

const routeDot: Record<RouteQuality, string> = {
  Good:    "bg-[var(--color-success)]",
  Average: "bg-[var(--color-edify-orange)]",
  Poor:    "bg-[var(--color-danger)]",
};

const routeLabel: Record<RouteQuality, string> = {
  Good:    "text-[var(--color-success)]",
  Average: "text-[var(--color-edify-orange)]",
  Poor:    "text-[var(--color-danger)]",
};

export function SmartRouteCapacityCard() {
  return (
    <SectionCard
      icon={<Route size={13} />}
      title="Smart Route & Capacity"
      actions={
        <a
          className="text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]"
          href="#smart-route"
        >
          View route planner →
        </a>
      }
    >
      {/* 4 mini KPIs — 2 across on narrow, 4 on md+. No ghost min-h so
          short labels don't reserve dead space. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {routeCapacityKpis.map((k, i) => {
          const Icon = iconMap[k.icon];
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4"][i] ?? "";
          return (
            <div
              key={k.key}
              className={cn(
                "card-elevated card-lift cursor-default tile-in p-2.5 overflow-hidden",
                staggerCls,
              )}
            >
              <div className="flex items-start gap-2">
                <span className={cn("w-7 h-7 rounded-md grid place-items-center shrink-0", toneFrame[k.tone])}>
                  <Icon size={13} />
                </span>
                <div className="min-w-0 flex-1 text-[var(--text-caption)] muted font-semibold leading-tight">
                  {k.label}
                </div>
              </div>
              <div className="text-[var(--text-h-sm)] font-extrabold tabular mt-1.5 leading-none truncate">{k.value}</div>
              {k.caption && <div className="text-[var(--text-tiny)] muted mt-0.5 truncate">{k.caption}</div>}
            </div>
          );
        })}
      </div>

      {/* Route Quality Table — hide secondary columns at narrow widths so
          the table no longer needs horizontal scroll. */}
      <div className="mt-3 overflow-x-auto scrollbar -mx-1 px-1">
        <div className="text-[var(--text-body)] font-bold mb-1.5">Route Quality by Team</div>
        <table className="w-full dtable">
          <thead>
            <tr className="bg-[var(--color-edify-soft)]/60">
              <th scope="col" className="text-left">CCEO</th>
              <th scope="col" className="text-left">Route Quality</th>
              <th scope="col" className="text-right hidden md:table-cell">On Time</th>
              <th scope="col" className="text-right hidden lg:table-cell">Avg. Travel</th>
              <th scope="col" className="text-right">Efficiency</th>
            </tr>
          </thead>
          <tbody>
            {routeCceoTable.map((r) => (
              <tr key={r.cceo} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="text-[var(--text-body)] font-semibold whitespace-nowrap">{r.cceo}</td>
                <td>
                  <span className="inline-flex items-center gap-1.5">
                    <span className={cn("w-2 h-2 rounded-full inline-block", routeDot[r.routeQuality])} />
                    <span className={cn("text-[var(--text-body)] font-semibold", routeLabel[r.routeQuality])}>
                      {r.routeQuality}
                    </span>
                  </span>
                </td>
                <td className="text-right tabular text-[var(--text-body)] hidden md:table-cell">{r.onTimeVisitsPct}%</td>
                <td className="text-right tabular text-[var(--text-body)] hidden lg:table-cell">{r.avgTravelTime}</td>
                <td className="text-right tabular text-[var(--text-body)] font-semibold">{r.efficiencyPct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[var(--text-caption)] muted leading-snug">
        Smart Route Planner is <span className="font-semibold text-[var(--color-edify-text)]">guidance, not control</span>.
        CCEOs may accept, ignore, or adjust suggestions when local conditions change.
      </div>
    </SectionCard>
  );
}
