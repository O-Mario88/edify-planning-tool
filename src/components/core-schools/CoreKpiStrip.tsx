"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
} from "recharts";
import {
  AlertOctagon,
  ArrowUpRight,
  CalendarOff,
  CalendarX,
  CheckCircle2,
  Clock,
  Footprints,
  type LucideIcon,
} from "lucide-react";
import {
  type CorePackageSummary,
  interventionYoy,
} from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

// One premium KPI strip replaces the 9 flat tiles. Tells the *story*
// of Core School health in one read:
//
//   LEFT  (5/12)  — Avg SSA hero metric + YoY delta + sparkline derived
//                   from the intervention YoY dataset
//   RIGHT (7/12)  — Package completion funnel (Complete → Nearly →
//                   Halfway → Started → Not Started) as stacked bars
//                   with school counts
//   BOTTOM (full) — Risk triage: 0 SSA · 0 Visits · 0 Training as 3
//                   rose chips so the critical-zero signals are
//                   unmissable instead of buried in positions 6/7/8.
export function CoreKpiStrip({ s }: { s: CorePackageSummary }) {
  const total = Math.max(s.totalCoreSchools, 1);

  // Average YoY change across all 8 interventions — used as the
  // sparkline narrative (prior → current).
  const avgYoyDelta = +(
    interventionYoy.reduce((a, r) => a + r.change, 0) / interventionYoy.length
  ).toFixed(2);

  // 6-month synthetic spark — interpolated from interventionYoy so the
  // visual matches the data narrative. Real backend would pass a true
  // 6-month average history.
  const sparkData = synthesizeSpark(s.averageSsa, avgYoyDelta);

  // The package funnel in order: Complete (best) → Started (entry).
  // Counts pulled straight from the summary so the bar widths stay
  // proportional to the same totals.
  const funnel = [
    { key: "complete",  label: "Package Complete", count: s.coreSchoolsWithFourVisitsFourTrainings,    tone: "good"      as const, icon: CheckCircle2 },
    { key: "nearly",    label: "Nearly Complete",  count: s.coreSchoolsWithThreeVisitsThreeTrainings,  tone: "good-soft" as const, icon: CheckCircle2 },
    { key: "halfway",   label: "Halfway",          count: s.coreSchoolsWithTwoVisitsTwoTrainings,      tone: "watch"     as const, icon: Clock        },
    { key: "started",   label: "Just Started",     count: s.coreSchoolsWithOneVisitOneTraining,        tone: "info"      as const, icon: Clock        },
    { key: "behind",    label: "Behind Schedule",  count: s.behindSchedule,                            tone: "warn"      as const, icon: AlertOctagon },
  ];

  return (
    <section className="card p-3.5 lg:p-5 flex flex-col gap-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 lg:gap-6 items-stretch">
        {/* LEFT — hero SSA metric */}
        <div className="lg:col-span-5 flex flex-col gap-2 lg:border-r lg:border-[#eef2f4] lg:pr-6">
          <div className="text-caption uppercase tracking-[0.12em] muted font-bold">
            Average Core SSA
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[44px] lg:text-[52px] font-extrabold leading-none tabular text-slate-900">
              {s.averageSsa.toFixed(1)}
            </span>
            <span className="text-[16px] muted font-semibold leading-none">/10</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap text-[11.5px]">
            <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
              <ArrowUpRight size={12} />
              +{avgYoyDelta.toFixed(2)}
            </span>
            <span className="muted font-semibold">YoY · all 8 interventions</span>
          </div>
          <div className="h-14 -mx-1 mt-1">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={sparkData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="core-kpi-spark" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%"  stopColor="#10b981" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="score"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#core-kpi-spark)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="text-caption muted font-semibold">
            Cohort improving across every intervention vs prior FY.
          </div>
        </div>

        {/* RIGHT — package completion funnel */}
        <div className="lg:col-span-7 flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-caption uppercase tracking-[0.12em] muted font-bold">
              Package Completion Funnel
            </div>
            <div className="text-[11px] muted font-semibold tabular">
              {s.totalCoreSchools} schools tracked
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {funnel.map((r) => {
              const { key, ...rest } = r;
              return <FunnelRow key={key} {...rest} total={total} />;
            })}
          </div>
          <div className="text-[11px] muted leading-snug mt-0.5">
            {s.coreSchoolsWithFourVisitsFourTrainings} of {s.totalCoreSchools} schools have the full 4-visits + 4-trainings package this FY.
          </div>
        </div>
      </div>

      {/* BOTTOM — Risk triage strip (Critical zeros pulled into the
          spotlight so they aren't buried in a long KPI row). */}
      <div className="rounded-xl border border-rose-200 bg-gradient-to-br from-rose-50 to-white p-3 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <RiskChip
          icon={CalendarX}
          label="0 SSA"
          count={s.coreSchoolsWithZeroSsa}
          caption="no SSA on file this FY"
        />
        <RiskChip
          icon={Footprints}
          label="0 Visits"
          count={s.coreSchoolsWithZeroVisits}
          caption="no staff or certified-partner visits"
        />
        <RiskChip
          icon={CalendarOff}
          label="0 Training"
          count={s.coreSchoolsWithZeroTraining}
          caption="no trainings delivered"
        />
      </div>
    </section>
  );
}

// ───────────── FunnelRow ─────────────

type FunnelTone = "good" | "good-soft" | "watch" | "warn" | "info";

const FUNNEL_TONE: Record<FunnelTone, { bar: string; chipBg: string; chipText: string; iconText: string }> = {
  good:        { bar: "bg-emerald-600", chipBg: "bg-emerald-100", chipText: "text-emerald-800", iconText: "text-emerald-700" },
  "good-soft": { bar: "bg-emerald-400", chipBg: "bg-emerald-50",  chipText: "text-emerald-700", iconText: "text-emerald-600" },
  watch:       { bar: "bg-amber-500",   chipBg: "bg-amber-50",    chipText: "text-amber-700",   iconText: "text-amber-600"   },
  info:        { bar: "bg-sky-500",     chipBg: "bg-sky-50",      chipText: "text-sky-700",     iconText: "text-sky-600"     },
  warn:        { bar: "bg-rose-500",    chipBg: "bg-rose-50",     chipText: "text-rose-700",    iconText: "text-rose-600"    },
};

function FunnelRow({
  label,
  count,
  total,
  tone,
  icon: Icon,
}: {
  label: string;
  count: number;
  total: number;
  tone: FunnelTone;
  icon: LucideIcon;
}) {
  const t = FUNNEL_TONE[tone];
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-1.5 w-[140px] shrink-0">
        <Icon size={12} className={t.iconText} />
        <span className="text-[11.5px] font-bold text-slate-700 truncate">{label}</span>
      </div>
      <div className="flex-1 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", t.bar)}
          style={{ width: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
        />
      </div>
      <div
        className={cn(
          "inline-flex items-center gap-1.5 px-2 py-[2px] rounded-md text-[11.5px] font-extrabold tabular w-[92px] justify-end shrink-0",
          t.chipBg,
          t.chipText,
        )}
      >
        <span>{pct}%</span>
        <span className="opacity-70 font-semibold">·</span>
        <span>{count}</span>
      </div>
    </div>
  );
}

// ───────────── RiskChip ─────────────

function RiskChip({
  icon: Icon,
  label,
  count,
  caption,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
  caption: string;
}) {
  return (
    <div className="rounded-lg bg-white border border-rose-200 p-2.5 flex items-start gap-2.5">
      <span className="w-9 h-9 rounded-lg grid place-items-center shrink-0 bg-rose-100 text-rose-700">
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-wide text-rose-700">
          {label}
        </div>
        <div className="text-[20px] font-extrabold tabular leading-none mt-0.5 text-rose-800">
          {count}
        </div>
        <div className="text-caption muted font-semibold mt-0.5 truncate">{caption}</div>
      </div>
    </div>
  );
}

// ───────────── Helpers ─────────────

// Synthesize a smooth 6-point ascent ending at the current SSA — gives
// the sparkline visual continuity with the "+YoY" headline without
// needing a real history feed in the demo.
function synthesizeSpark(current: number, totalDelta: number): { x: number; score: number }[] {
  const start = +(current - totalDelta).toFixed(2);
  const points = 6;
  const step = (current - start) / (points - 1);
  return Array.from({ length: points }, (_, i) => ({
    x: i,
    score: +(start + step * i + (i === points - 1 ? 0 : (Math.sin(i * 1.6) * 0.04))).toFixed(2),
  }));
}
