"use client";

import { ArrowDownRight, ArrowUpRight, Cloud } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, ResponsiveContainer } from "recharts";
import { replicaKpis, type ReplicaKpi, type ReplicaKpiVisual } from "@/lib/core-school-replica-mock";
import { cn } from "@/lib/utils";
import { InteractiveTile } from "@/components/tile-filter";

// Each KPI key maps to a tile filter id from the Core School registry.
// Tiles without a meaningful underlying record list (none in the KPI
// row today) would map to undefined and render as non-clickable.
const KPI_FILTER_ID: Record<string, string | undefined> = {
  total:      "total",
  assessed:   "ssa-complete",
  avg_ssa:    "avg-ssa",
  on_track:   "on-track",
  behind:     "behind-schedule",
  critical:   "critical-gap",
  salesforce: "salesforce-compliance",
};

// 7 KPI tiles row — every meaningful KPI is a clickable filter trigger
// that drills the page to the exact subset behind the number.
export function ReplicaKpiRow({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 lg:gap-2.5">
      {replicaKpis.map((k, i) => {
        const filterId = KPI_FILTER_ID[k.key];
        const active = !!filterId && activeFilterId === filterId;
        return (
          <KpiTile
            key={k.key}
            k={k}
            idx={i}
            active={active}
            onClick={
              filterId && onTileClick ? () => onTileClick(filterId) : undefined
            }
          />
        );
      })}
    </section>
  );
}

function KpiTile({
  k,
  idx,
  active,
  onClick,
}: {
  k: ReplicaKpi;
  idx: number;
  active: boolean;
  onClick?: () => void;
}) {
  const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7"][idx] ?? "";
  const className = cn(
    "card card-lift tile-in rounded-xl p-3 flex flex-col gap-1.5 min-h-[124px] sm:min-h-[112px]",
    staggerCls,
  );
  const body = (
    <>
      <div className="text-[9.5px] sm:text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2 min-h-[24px]">
        {k.label}
      </div>

      <div className="flex items-end justify-between gap-2 flex-1">
        <div className="min-w-0 flex flex-col gap-0.5 flex-1">
          <div className="flex items-baseline gap-1 flex-wrap">
            <span className="text-[22px] sm:text-[24px] font-extrabold tabular leading-none text-slate-900 num-hero glow-emerald">
              {k.value}
            </span>
            {k.subValue && (
              <span className="text-[11px] muted font-semibold leading-none truncate">
                {k.subValue}
              </span>
            )}
          </div>
          {k.delta && (
            <div className="flex items-center gap-1 mt-0.5 flex-wrap">
              {k.deltaTone === "up" ? (
                <ArrowUpRight size={10} className="text-emerald-600 shrink-0" />
              ) : (
                <ArrowDownRight size={10} className="text-rose-600 shrink-0" />
              )}
              <span className={cn(
                "text-[10px] font-extrabold tabular",
                k.deltaTone === "up" ? "text-emerald-700" : "text-rose-700",
              )}>
                {k.delta}
              </span>
              {k.caption && (
                <span className="text-[9.5px] muted font-semibold truncate">
                  {k.caption}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="shrink-0">
          <Visual v={k.visual} />
        </div>
      </div>
    </>
  );

  if (!onClick) {
    return (
      <InteractiveTile asStatic active={active} className={className}>
        {body}
      </InteractiveTile>
    );
  }
  return (
    <InteractiveTile onClick={onClick} active={active} className={className}>
      {body}
    </InteractiveTile>
  );
}

function Visual({ v }: { v: ReplicaKpiVisual }) {
  if (v.kind === "bars") {
    const data = v.values.map((y, x) => ({ x, y }));
    return (
      <div className="w-12 h-8">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 1, right: 0, bottom: 0, left: 0 }}>
            <Bar dataKey="y" fill="#a78bfa" radius={[1, 1, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (v.kind === "line") {
    const data = v.values.map((y, x) => ({ x, y }));
    return (
      <div className="w-14 h-8">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 1, right: 0, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="kpi-line-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#a78bfa" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#a78bfa" stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="y" stroke="#8b5cf6" strokeWidth={1.5} fill="url(#kpi-line-grad)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (v.kind === "ring") {
    return <Ring pct={v.pct} tone={v.tone} />;
  }
  // brand glyph
  return (
    <span className="w-8 h-8 rounded-lg grid place-items-center bg-sky-100 text-sky-600">
      <Cloud size={15} />
    </span>
  );
}

function Ring({ pct, tone }: { pct: number; tone: "emerald" | "amber" | "rose" }) {
  const SIZE = 38;
  const STROKE = 5;
  const R = (SIZE - STROKE) / 2;
  const C = 2 * Math.PI * R;
  const dash = C * (1 - Math.max(0, Math.min(100, pct)) / 100);
  const color =
    tone === "emerald" ? "#10b981" : tone === "amber" ? "#f59e0b" : "#ef4444";
  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90">
      <circle cx={SIZE / 2} cy={SIZE / 2} r={R} stroke="#eef2f4" strokeWidth={STROKE} fill="none" />
      <circle cx={SIZE / 2} cy={SIZE / 2} r={R} stroke={color} strokeWidth={STROKE} fill="none" strokeDasharray={C} strokeDashoffset={dash} strokeLinecap="round" />
    </svg>
  );
}
