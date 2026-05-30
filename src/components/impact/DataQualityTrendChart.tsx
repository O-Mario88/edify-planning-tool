"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { ChevronDown, Info } from "lucide-react";
import { qualityTrend } from "@/lib/impact-mock";

export function DataQualityTrendChart() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-1.5">
          Data Quality Trend
          <Info size={11} className="text-[var(--color-edify-muted)]" />
        </h2>
        <button
          type="button"
          className="h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold inline-flex items-center gap-1"
        >
          Last 6 Months
          <ChevronDown size={11} className="text-[var(--color-edify-muted)]" />
        </button>
      </header>

      <div className="flex-1 -mx-1.5" style={{ minHeight: 240 }}>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={qualityTrend} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef2f4" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              ticks={[0, 2000, 4000, 6000, 8000]}
              tickFormatter={(v) => (v === 0 ? "0" : `${v / 1000}K`)}
              tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 8 }}
              formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
            />
            <Legend
              iconType="circle"
              iconSize={7}
              wrapperStyle={{ fontSize: 10.5, paddingBottom: 6 }}
              verticalAlign="top"
              align="left"
            />
            <Line type="monotone" name="Verified"  dataKey="verified" stroke="#10b981" strokeWidth={2} dot={{ r: 3, fill: "#10b981" }} />
            <Line type="monotone" name="In Review" dataKey="inReview" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 3, fill: "#0ea5e9" }} />
            <Line type="monotone" name="Failed QC" dataKey="failedQc" stroke="#ef4444" strokeWidth={2} dot={{ r: 3, fill: "#ef4444" }} />
            <Line type="monotone" name="Resolved"  dataKey="resolved" stroke="#7c3aed" strokeWidth={2} dot={{ r: 3, fill: "#7c3aed" }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
