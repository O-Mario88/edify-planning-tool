"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
} from "recharts";
import {
  AlertOctagon,
  ArrowUpRight,
  CheckCircle2,
  Clock,
} from "lucide-react";
import { cceoKpis, coreSsaTrend } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// One premium KPI strip replaces the 6 flat tiles. Tells the *story*:
// the average SSA score on the left (hero metric + sparkline + trend),
// and the school-health funnel on the right (On Track / Behind /
// Critical as stacked horizontal bars with school counts).
//
// Numbers come from the existing `cceoKpis` so the strip and any other
// KPI surface stay in lock-step.
export function CceoKpiStrip() {
  // Pull the four numbers the strip needs out of the canonical KPI
  // dataset. Defensive lookups so the layout never crashes if the mock
  // shape drifts.
  const avgSsa   = cceoKpis.find((k) => k.key === "avg_ssa");
  const onTrack  = cceoKpis.find((k) => k.key === "on_track");
  const behind   = cceoKpis.find((k) => k.key === "behind");
  const critical = cceoKpis.find((k) => k.key === "critical");

  // Total school count drives the funnel-row count column. Pull from
  // the Total Core Schools KPI for consistency.
  const totalCore = cceoKpis.find((k) => k.key === "total_core");
  const totalCoreCount = totalCore ? Number(totalCore.value.replace(/,/g, "")) : 128;

  const funnelRows = [
    {
      key:   "on_track",
      label: "On Track",
      pct:   percentFromKpi(onTrack),
      count: countFor(onTrack, totalCoreCount, "on_track"),
      tone:  "good" as const,
      icon:  CheckCircle2,
    },
    {
      key:   "behind",
      label: "Behind",
      pct:   percentFromKpi(behind),
      count: countFor(behind, totalCoreCount, "behind"),
      tone:  "watch" as const,
      icon:  Clock,
    },
    {
      key:   "critical",
      label: "Critical",
      pct:   percentFromKpi(critical),
      count: countFor(critical, totalCoreCount, "critical"),
      tone:  "warn" as const,
      icon:  AlertOctagon,
    },
  ];

  return (
    <section className="card p-3.5 lg:p-4 grid grid-cols-1 lg:grid-cols-12 gap-5 lg:gap-6 items-stretch">
      {/* LEFT — hero metric (SSA score + sparkline + trend). */}
      <div className="lg:col-span-5 flex flex-col gap-2 lg:border-r lg:border-[#eef2f4] lg:pr-6">
        <div className="text-caption uppercase tracking-[0.12em] muted font-bold">
          Average SSA Score
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[44px] lg:text-[52px] font-extrabold leading-none tabular text-slate-900">
            {avgSsa?.value ?? "7.6"}
          </span>
          <span className="text-[16px] muted font-semibold leading-none">
            {avgSsa?.subValue ?? "/10"}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap text-[11.5px]">
          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
            <ArrowUpRight size={12} />
            +{avgSsa?.trendDelta ?? "0.3"}
          </span>
          <span className="muted font-semibold">{avgSsa?.trendSuffix ?? "vs Apr 2025"}</span>
        </div>
        <div className="h-14 -mx-1 mt-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={coreSsaTrend} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="cceo-kpi-spark" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#10b981" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="score"
                stroke="#10b981"
                strokeWidth={2}
                fill="url(#cceo-kpi-spark)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="text-caption muted font-semibold">
          {coreSsaTrend.length}-month trend · {coreSsaTrend[0].month}–{coreSsaTrend[coreSsaTrend.length - 1].month}
        </div>
      </div>

      {/* RIGHT — health funnel.  One segmented partition bar showing
          the three terminal states, plus detail rows below.  Mirrors
          the IA Verification Funnel treatment for cross-dashboard
          consistency. */}
      <div className="lg:col-span-7 flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-caption uppercase tracking-[0.12em] muted font-bold">
            Health Funnel
          </div>
          <div className="text-[11px] muted font-semibold tabular">
            {totalCoreCount} schools tracked
          </div>
        </div>

        {/* Segmented partition rail. */}
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--color-edify-divider)]">
          {funnelRows.map((r) => (
            <div
              key={r.key}
              className={cn("h-full transition-[width] duration-500", FUNNEL_TONE[r.tone].bar)}
              style={{ width: `${r.pct}%` }}
              title={`${r.label}: ${r.count} schools (${r.pct}%)`}
            />
          ))}
        </div>

        {/* Detail rows. */}
        <ul className="mt-1 space-y-2">
          {funnelRows.map((r) => {
            const t = FUNNEL_TONE[r.tone];
            const Icon = r.icon;
            return (
              <li key={r.key} className="flex items-center gap-2.5">
                <span className={cn("w-2 h-2 rounded-full shrink-0", t.bar)} />
                <Icon size={12} className={t.iconText} />
                <span className="t-body-lg font-bold flex-1 min-w-0">{r.label}</span>
                <span className="num-hero text-[14px] font-extrabold tabular text-[var(--text-primary)]">
                  {r.count}
                </span>
                <span className="t-caption text-muted tabular w-12 text-right">
                  {r.pct}%
                </span>
              </li>
            );
          })}
        </ul>

        <p className="mt-1 t-caption text-muted leading-snug">
          70% on track this month — keep the 9% critical from growing by booking visits this week.
        </p>
      </div>
    </section>
  );
}

// ───────────── Tone palette ─────────────

type FunnelTone = "good" | "watch" | "warn";

const FUNNEL_TONE: Record<FunnelTone, { bar: string; chipBg: string; chipText: string; iconText: string }> = {
  good:  { bar: "bg-emerald-500", chipBg: "bg-emerald-50",  chipText: "text-emerald-700", iconText: "text-emerald-600" },
  watch: { bar: "bg-amber-500",   chipBg: "bg-amber-50",    chipText: "text-amber-700",   iconText: "text-amber-600"   },
  warn:  { bar: "bg-rose-500",    chipBg: "bg-rose-50",     chipText: "text-rose-700",    iconText: "text-rose-600"    },
};

// ───────────── Helpers ─────────────

function percentFromKpi(k: typeof cceoKpis[number] | undefined): number {
  if (!k) return 0;
  // The KPI sub-value is wrapped in parens like "(70%)". Strip it down.
  const sub = k.subValue ?? "";
  const m = sub.match(/(\d+(?:\.\d+)?)%/);
  if (m) return Number(m[1]);
  // Fallback: try the trendDelta for percentages.
  const t = k.trendDelta.match(/(\d+(?:\.\d+)?)/);
  return t ? Number(t[1]) : 0;
}

function countFor(k: typeof cceoKpis[number] | undefined, total: number, _key: string): number {
  // The KPI's `value` is the raw count (e.g., 89, 27, 12). If it's
  // missing or not numeric, derive it from total × pct as a fallback.
  void _key;
  if (!k) return 0;
  const v = Number(String(k.value).replace(/,/g, ""));
  if (Number.isFinite(v) && v > 0) return v;
  return Math.round(total * percentFromKpi(k) / 100);
}
