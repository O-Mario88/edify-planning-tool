"use client";

import {
  Building2,
  Download,
  Info,
  MapPin,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { districtSsaPerformance } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

function scoreColor(s: number) {
  if (s >= 7.5) return "text-emerald-700";
  if (s >= 6.0) return "text-amber-700";
  if (s >= 4.5) return "text-orange-700";
  return "text-rose-700";
}

function scoreEdge(s: number) {
  if (s >= 7.5) return "border-l-emerald-500";
  if (s >= 6.0) return "border-l-amber-500";
  if (s >= 4.5) return "border-l-orange-500";
  return "border-l-rose-500 bg-rose-50/30";
}

export function DistrictSsaPerformanceTable() {
  return (
    <SectionCard
      icon={<Building2 size={13} />}
      title="District SSA Performance"
      actions={
        <div className="flex items-center gap-2">
          <Info size={13} className="text-[var(--color-edify-muted)]" />
          <button type="button" className="btn btn-sm">
            <Download size={12} />
            Export
          </button>
        </div>
      }
    >
      {/* Mobile-stacked variant — one card per district, color-coded
          left edge by score tier, hero score on the right, weakness
          and high-risk count below, trend pill at the bottom. */}
      <div className="md:hidden space-y-2">
        {districtSsaPerformance.map((d) => {
          const up = d.trend === "up";
          const TrendIcon = up ? TrendingUp : TrendingDown;
          return (
            <div
              key={d.district}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-3 space-y-2",
                scoreEdge(d.averageScore),
              )}
            >
              <div className="flex items-start gap-2.5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white text-[11px] font-extrabold grid place-items-center shrink-0 shadow-sm">
                  {d.rank}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900 inline-flex items-center gap-1.5">
                    <MapPin size={11} className="text-[var(--color-edify-muted)]" />
                    {d.district}
                  </div>
                  <div className="text-caption muted leading-tight mt-0.5 tabular">
                    {d.schoolsAssessed} schools assessed · {d.completionRate.toFixed(1)}% completion
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className={cn("text-[20px] font-extrabold tabular leading-none", scoreColor(d.averageScore))}>
                    {d.averageScore.toFixed(2)}
                  </div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">
                    /10 SSA
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 flex-wrap text-caption">
                <span className="text-slate-700 leading-snug">
                  <span className="muted font-semibold">Weakness:</span>{" "}
                  <span className="font-semibold">{d.highestWeakness}</span>
                </span>
                <span className="inline-flex items-center gap-1 font-bold text-rose-700 tabular whitespace-nowrap">
                  {d.highRiskSchools} high-risk
                </span>
              </div>

              <div className="flex items-center justify-end">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[10px] font-bold",
                    up ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
                  )}
                >
                  <TrendIcon size={11} />
                  {up ? "Up" : "Down"} vs Q3
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table — gradient header, hover rows, sticky #1 column. */}
      <div className="hidden md:block overflow-x-auto -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2 px-2">#</th>
              <th scope="col" className="text-left font-bold py-2 px-2">District</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Schools</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Avg Score ↓</th>
              <th scope="col" className="text-left font-bold py-2 px-2">Highest Weakness</th>
              <th scope="col" className="text-right font-bold py-2 px-2">High-Risk</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Completion</th>
              <th scope="col" className="text-right font-bold py-2 px-2">Trend</th>
            </tr>
          </thead>
          <tbody>
            {districtSsaPerformance.map((d, idx) => {
              const last = idx === districtSsaPerformance.length - 1;
              return (
                <tr
                  key={d.district}
                  className={cn("transition-colors hover:bg-[var(--color-edify-soft)]/40", !last && "border-b border-[#eef2f4]")}
                >
                  <td className="py-2 px-2 font-extrabold tabular">{d.rank}</td>
                  <td className="py-2 px-2 font-semibold whitespace-nowrap">{d.district}</td>
                  <td className="py-2 px-2 text-right tabular">{d.schoolsAssessed}</td>
                  <td className={cn("py-2 px-2 text-right tabular text-[13px] font-extrabold", scoreColor(d.averageScore))}>
                    {d.averageScore.toFixed(2)}
                  </td>
                  <td className="py-2 px-2 muted">{d.highestWeakness}</td>
                  <td className="py-2 px-2 text-right tabular text-rose-700 font-bold">
                    {d.highRiskSchools}
                  </td>
                  <td className="py-2 px-2 text-right tabular">{d.completionRate.toFixed(1)}%</td>
                  <td className="py-2 px-2 text-right">
                    {d.trend === "up" ? (
                      <TrendingUp size={14} className="inline text-[var(--color-success)]" />
                    ) : (
                      <TrendingDown size={14} className="inline text-[var(--color-danger)]" />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[11px] muted">
        Showing 1 to {districtSsaPerformance.length} of {districtSsaPerformance.length} districts
      </div>
    </SectionCard>
  );
}
