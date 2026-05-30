"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { LineChart as LineChartIcon, TrendingUp } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { paceForecast } from "@/lib/my-targets-billion-mock";
import { cn } from "@/lib/utils";

// This Month Pace & Forecast — line chart Expected vs Actual (Actual
// stops at current week, with the current-pace marker pinned over it)
// + a 4-row weekly breakdown table + a one-line month forecast.
export function PaceForecastCard() {
  const p = paceForecast;
  const currentWeekRow = p.chart.find((r) => r.actual !== null && p.chart.indexOf(r) === 1) ?? p.chart[1];

  return (
    <SectionCard
      icon={<LineChartIcon size={13} />}
      title="This Month Pace & Forecast"
      actions={
        <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-50 text-amber-700 border border-amber-200">
          {p.status}
        </span>
      }
    >
      <div className="h-[200px] -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={p.chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="pace-expected" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="#3257d9" stopOpacity={0.18} />
                <stop offset="100%" stopColor="#3257d9" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#eef2f4" vertical={false} />
            <XAxis
              dataKey="week"
              tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v) => `${v}%`}
              tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
              width={32}
            />
            <Tooltip
              contentStyle={{ borderRadius: 8, border: "1px solid #d8e3e8", fontSize: 11, fontFamily: "inherit" }}
              labelStyle={{ fontWeight: 700, color: "#0f1720" }}
              formatter={(v) => (typeof v === "number" ? [`${v}%`, ""] : [String(v), ""])}
            />
            <Legend
              verticalAlign="top"
              height={20}
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 10, color: "#647782" }}
            />
            <Line
              type="monotone"
              dataKey="expected"
              name="Expected Pace"
              stroke="#3257d9"
              strokeDasharray="4 3"
              strokeWidth={1.8}
              dot={{ r: 2.5, fill: "#3257d9", stroke: "#ffffff", strokeWidth: 1 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual Pace"
              stroke="#10b981"
              strokeWidth={2.4}
              dot={{ r: 3, fill: "#10b981", stroke: "#ffffff", strokeWidth: 1 }}
              connectNulls={false}
              isAnimationActive={false}
            />
            {currentWeekRow.actual !== null && (
              <ReferenceDot
                x={currentWeekRow.week}
                y={currentWeekRow.actual}
                r={5}
                fill="#10b981"
                stroke="#ffffff"
                strokeWidth={2}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* "Current 42%" callout — informational subtitle replaces the
          inline annotation that doesn't survive a chart resize. */}
      <div className="-mt-1 mb-2 text-caption muted inline-flex items-center gap-1.5">
        <TrendingUp size={11} className="text-emerald-600" />
        <span>
          Current actual pace:{" "}
          <span className="font-extrabold text-slate-900">{p.currentPct}%</span>
        </span>
      </div>

      {/* Weekly breakdown — activity counts (Planned / Completed /
          Remaining) per week. The active week gets a soft tinted
          background so the eye lands on it first. */}
      <div className="text-[10px] uppercase tracking-wide muted font-bold mb-1.5">
        Weekly Breakdown (May)
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {p.weekly.map((w) => (
          <div
            key={w.week}
            className={cn(
              "rounded-lg border p-2 text-[10px] leading-tight",
              w.active
                ? "bg-emerald-50/60 border-emerald-200"
                : "bg-white border-[var(--color-edify-border)]",
            )}
          >
            <div className="font-bold text-slate-700">{w.week}</div>
            <div className="muted font-semibold mt-0.5">Planned</div>
            <div className="text-[12px] font-extrabold tabular text-slate-900 leading-tight mt-0.5">{w.plannedCount}</div>
            <div className="muted font-semibold mt-1">Completed</div>
            <div className={cn("text-[11px] font-bold tabular", w.active ? "text-emerald-700" : "text-slate-700")}>
              {w.completedCount}
            </div>
            <div className="muted font-semibold mt-1">Remaining</div>
            <div className={cn("text-[11px] font-bold tabular", w.remainingCount === 0 ? "text-emerald-700" : "text-slate-700")}>
              {w.remainingCount}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] muted leading-snug">
        <span className="font-bold text-slate-700">Month Forecast:</span>{" "}
        <span className="text-emerald-700 font-extrabold">{p.forecastPct}%</span> {p.forecastNote}.
      </div>
    </SectionCard>
  );
}
