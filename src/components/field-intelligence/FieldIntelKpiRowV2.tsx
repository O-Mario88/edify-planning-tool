"use client";

import {
  Calendar,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  Target,
  TrendingUp,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

// 6 KPI tiles for the Daily Field Debrief page. Each card sits flush in
// a single row at lg+; wraps at smaller widths.

type KpiTile = {
  key: string;
  label: string;
  value: string;
  delta: string;
  Icon: LucideIcon;
  iconBg: string;
  iconText: string;
};

export function FieldIntelKpiRowV2({
  planned,
  completed,
  verified,
  incomplete,
  rawAchievementPct,
  contextAdjustedPct,
}: {
  planned: number;
  completed: number;
  verified: number;
  incomplete: number;
  rawAchievementPct: number;
  contextAdjustedPct: number;
}) {
  const tiles: KpiTile[] = [
    { key: "planned",     label: "Planned",          value: String(planned),               delta: "↑25% ", Icon: Calendar,    iconBg: "bg-sky-100",    iconText: "text-sky-700"    },
    { key: "completed",   label: "Completed",        value: String(completed),             delta: "↑20% ", Icon: CheckCircle2, iconBg: "bg-emerald-100", iconText: "text-emerald-700" },
    { key: "verified",    label: "Verified",         value: String(verified),              delta: "↑50% ", Icon: ShieldCheck, iconBg: "bg-emerald-100",iconText: "text-emerald-700"},
    { key: "incomplete",  label: "Incomplete",       value: String(incomplete),            delta: "↑100%", Icon: XCircle,     iconBg: "bg-rose-100",   iconText: "text-rose-700"   },
    { key: "raw",         label: "Raw Achievement",  value: `${rawAchievementPct}%`,       delta: "↑10pp", Icon: Target,      iconBg: "bg-violet-100", iconText: "text-violet-700" },
    { key: "ctx",         label: "Context-Adjusted", value: `${contextAdjustedPct}%`,      delta: "↑8pp ", Icon: TrendingUp,  iconBg: "bg-emerald-100",iconText: "text-emerald-700"},
  ];

  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {tiles.map((t) => (
        <article key={t.key} className="card p-3.5 flex flex-col">
          <div className="flex items-start gap-2.5">
            <span className={cn("h-9 w-9 rounded-xl grid place-items-center shrink-0", t.iconBg, t.iconText)}>
              <t.Icon size={16} />
            </span>
            <div className="min-w-0">
              <div className="text-[11.5px] muted font-semibold leading-tight truncate">{t.label}</div>
              <div className="text-[24px] font-extrabold tabular leading-none mt-0.5">{t.value}</div>
            </div>
          </div>
          <div className="mt-2 inline-flex items-center gap-1 text-caption muted font-semibold">
            vs last month
            <span className="text-emerald-600 inline-flex items-center gap-0.5 ml-auto">
              <ArrowUpRight size={11} />
              {t.delta.trim()}
            </span>
          </div>
        </article>
      ))}
    </section>
  );
}
