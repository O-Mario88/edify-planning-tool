"use client";

import { ArrowUpRight, BookOpen, GraduationCap, Heart, Map, ScrollText, Shield, Users, Wallet, Scale, type LucideIcon } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import {
  replicaHeatmap,
  replicaInterventionScores,
  replicaInterventionYoy,
  type ReplicaInterventionRow,
} from "@/lib/core-school-replica-mock";
import { cn } from "@/lib/utils";

const INT_ICON: Record<string, LucideIcon> = {
  "Christ-like Behavior":         Heart,
  "Exposure to the Word of God":  BookOpen,
  "Fees / Budget / Accounts":     Wallet,
  "Government Requirements":      Scale,
  "Leadership Best Practice":     Shield,
  "Learning Environment":         ScrollText,
  "Teaching Environment":         GraduationCap,
  "Enrollment":                   Users,
};

// 3-column analytics row — Intervention bars + District heatmap + YoY
// comparison. The standalone "Core SSA Average Trend" card was removed
// because the same monthly read is already surfaced inside the
// Average Core SSA Score KPI tile (with its mini line + delta), so a
// dedicated 220-px card duplicated that view.
export function ReplicaAnalyticsRow() {
  return (
    <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
      <div className="col-span-12 md:col-span-6 xl:col-span-4">
        <SsaPerformanceByIntervention />
      </div>
      <div className="col-span-12 md:col-span-6 xl:col-span-4">
        <CoreSsaHeatmap />
      </div>
      <div className="col-span-12 md:col-span-12 xl:col-span-4">
        <InterventionYoyComparison />
      </div>
    </section>
  );
}

// ───────────── SSA Performance by Intervention ─────────────

function SsaPerformanceByIntervention() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-1.5 min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight truncate">SSA Performance by Intervention</h3>
          <span className="text-[10px] muted font-semibold">(Average Score)</span>
        </div>
        <button className="text-[11px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 whitespace-nowrap">
          View Details
        </button>
      </header>

      <ul className="flex-1 flex flex-col justify-between gap-1.5">
        {replicaInterventionScores.map((row) => (
          <InterventionBar key={row.rank} row={row} />
        ))}
        <div className="flex justify-between text-[9.5px] muted tabular px-2 pt-1">
          {[0, 2, 4, 6, 8, 10].map((v) => (<span key={v}>{v}</span>))}
        </div>
      </ul>
    </article>
  );
}

function InterventionBar({ row }: { row: ReplicaInterventionRow }) {
  const Icon = INT_ICON[row.intervention] ?? Heart;
  const color = row.score >= 7.5 ? "#10b981" : row.score >= 6.5 ? "#f59e0b" : "#ef4444";
  const pct = (row.score / 10) * 100;
  return (
    <li className="flex items-center gap-1.5">
      <span className="w-5 text-[10px] tabular muted font-bold text-center shrink-0">{row.rank}</span>
      <Icon size={11} className="text-slate-500 shrink-0" />
      <span className="text-caption font-semibold text-slate-700 flex-1 min-w-0 truncate">{row.intervention}</span>
      <div className="w-20 h-1.5 rounded-full bg-slate-100 overflow-hidden shrink-0">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-extrabold tabular shrink-0 w-7 text-right">{row.score.toFixed(1)}</span>
    </li>
  );
}

// ───────────── Core SSA Heatmap by District ─────────────

// The official 8 SSA interventions (display order matches the canonical list),
// with the average shown as a SEPARATE trailing column — never a replacement.
const HEAT_COLS = [
  { key: "christlike", label: "Christ-like Behavior" },
  { key: "wordOfGod",  label: "Exposure to the Word of God" },
  { key: "leadership", label: "Leadership Best Practice" },
  { key: "teaching",   label: "Teaching Environment" },
  { key: "learning",   label: "Learning Environment" },
  { key: "government", label: "Government Requirements" },
  { key: "fees",       label: "Fees / Budget / Accounts" },
  { key: "enrollment", label: "Enrollment" },
  { key: "avgRow",     label: "Avg Score" },
] as const;

function heatTone(score: number) {
  if (score >= 8.0) return { bg: "#10b981", text: "#ffffff" };
  if (score >= 7.5) return { bg: "#34d399", text: "#04331f" };
  if (score >= 7.0) return { bg: "#a7f3d0", text: "#065f46" };
  if (score >= 6.5) return { bg: "#fef3c7", text: "#92400e" };
  if (score >= 6.0) return { bg: "#fde68a", text: "#78350f" };
  if (score >= 5.5) return { bg: "#fecaca", text: "#991b1b" };
  return { bg: "#fca5a5", text: "#7f1d1d" };
}

function CoreSsaHeatmap() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-[13px] font-extrabold tracking-tight truncate">Core SSA Heatmap by District</h3>
        <button className="text-[11px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 whitespace-nowrap">
          View Map
        </button>
      </header>

      <div className="flex-1 overflow-x-auto -mx-1">
        <table className="w-full border-separate border-spacing-x-0.5 border-spacing-y-1 px-1">
          <thead>
            <tr>
              <th className="text-left text-[9px] muted font-bold uppercase tracking-wide pb-1">District</th>
              {HEAT_COLS.map((c) => (
                <th key={c.key} className="text-center text-[8.5px] muted font-bold leading-tight pb-1 px-0.5" title={c.label}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {replicaHeatmap.map((row) => (
              <tr key={row.district}>
                <td className="text-caption font-semibold whitespace-nowrap pr-1 inline-flex items-center gap-1">
                  <Map size={9} className="text-slate-400" />
                  {row.district}
                </td>
                {HEAT_COLS.map((c) => {
                  const score = row[c.key] as number;
                  const tone = heatTone(score);
                  return (
                    <td key={c.key} className="text-center align-middle">
                      <span
                        className="inline-block w-full min-w-[28px] py-1 rounded-md text-[10px] font-extrabold tabular"
                        style={{ backgroundColor: tone.bg, color: tone.text }}
                      >
                        {score.toFixed(1)}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

// ───────────── Intervention Performance YoY Comparison ─────────────

function InterventionYoyComparison() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-[13px] font-extrabold tracking-tight truncate">Intervention Performance YoY Comparison</h3>
        <button className="text-[11px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 whitespace-nowrap">
          View Full Report
        </button>
      </header>

      <div className="flex-1 overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-[9px] muted font-bold uppercase tracking-wide">
              <th className="text-left pb-1">Intervention</th>
              <th className="text-center pb-1 px-1">FY 2024<br/>Avg Score</th>
              <th className="text-center pb-1 px-1">FY 2025<br/>Avg Score</th>
              <th className="text-center pb-1 px-1">Change</th>
              <th className="text-right pb-1">Trend</th>
            </tr>
          </thead>
          <tbody>
            {replicaInterventionYoy.map((row) => (
              <tr key={row.intervention} className="border-t border-slate-100">
                <td className="text-caption font-semibold py-1.5 pr-1 max-w-[110px]">
                  <span className="block truncate">{row.intervention}</span>
                </td>
                <td className="text-center text-caption tabular font-bold py-1.5 px-1">{row.fy2024.toFixed(1)}</td>
                <td className="text-center text-caption tabular font-bold py-1.5 px-1">{row.fy2025.toFixed(1)}</td>
                <td className="text-center py-1.5 px-1">
                  <span className={cn(
                    "inline-flex items-center gap-0.5 text-caption font-extrabold tabular",
                    row.change > 0 ? "text-emerald-700" : "text-rose-700",
                  )}>
                    <ArrowUpRight size={9} className={row.change > 0 ? "" : "rotate-90"} />
                    {row.change > 0 ? "+" : ""}{row.change.toFixed(1)}
                  </span>
                </td>
                <td className="py-1.5 pl-1 text-right">
                  <span className="inline-block w-14 h-5 align-middle">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={row.trend.map((y, x) => ({ x, y }))}>
                        <defs>
                          <linearGradient id={`yoy-${row.intervention}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#10b981" stopOpacity={0.4} />
                            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <Area type="monotone" dataKey="y" stroke="#10b981" strokeWidth={1.5} fill={`url(#yoy-${row.intervention})`} isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
