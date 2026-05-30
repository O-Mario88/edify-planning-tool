"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { rvpKpis, type RvpKpi } from "@/lib/rvp-fund-approvals-mock";
import { cn } from "@/lib/utils";

export function RvpKpiRow() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {rvpKpis.map((k, i) => (
          <Tile key={k.key} k={k} idx={i} />
        ))}
      </div>
    </section>
  );
}

function Tile({ k, idx }: { k: RvpKpi; idx: number }) {
  const up = k.deltaTone === "up";
  const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][idx] ?? "";
  return (
    <div className={cn("card card-lift cursor-default tile-in p-3 flex flex-col gap-1.5", stagger)}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2 min-h-[24px]">
        {k.label}
      </div>

      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0 flex flex-col gap-0.5 flex-1">
          <span className="text-[18px] font-extrabold tabular leading-none text-slate-900 num-hero glow-emerald truncate">
            {k.value}
          </span>
        </div>
        {typeof k.ringPct === "number" && (
          <Ring pct={k.ringPct} />
        )}
      </div>

      <div className="flex items-center gap-1.5 text-caption min-w-0">
        {k.delta && (
          <span className={cn(
            "inline-flex items-center gap-0.5 font-bold shrink-0",
            up ? "text-emerald-700" : "text-emerald-700",
          )}>
            {up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
            {k.delta}
          </span>
        )}
        {(k.subValue || k.caption) && (
          <span className="muted font-semibold truncate">{k.subValue ?? k.caption}</span>
        )}
      </div>
    </div>
  );
}

function Ring({ pct }: { pct: number }) {
  const SIZE = 40;
  const STROKE = 5;
  const R = (SIZE - STROKE) / 2;
  const C = 2 * Math.PI * R;
  const dash = C * (1 - pct / 100);
  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90 shrink-0">
      <circle cx={SIZE/2} cy={SIZE/2} r={R} stroke="#eef2f4" strokeWidth={STROKE} fill="none" />
      <circle cx={SIZE/2} cy={SIZE/2} r={R} stroke="#3b82f6" strokeWidth={STROKE} fill="none"
              strokeDasharray={C} strokeDashoffset={dash} strokeLinecap="round" />
    </svg>
  );
}
