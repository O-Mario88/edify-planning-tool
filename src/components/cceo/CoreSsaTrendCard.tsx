"use client";

import Link from "next/link";
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  ReferenceDot,
  Area,
  ComposedChart,
} from "recharts";
import { ArrowUpRight, ArrowDownRight, LineChart as LineIcon, Sparkles, Target } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { coreSsaTrend, coreSsaTrendHighlight } from "@/lib/cceo-mock";

export function CoreSsaTrendCard() {
  const last  = coreSsaTrend[coreSsaTrend.length - 1];
  const first = coreSsaTrend[0];
  const prev  = coreSsaTrend[coreSsaTrend.length - 2];

  const totalDelta   = +(last.score - first.score).toFixed(1);
  const monthDelta   = +(last.score - prev.score).toFixed(1);
  const totalDeltaUp = totalDelta >= 0;
  const monthUp      = monthDelta >= 0;

  // Find the best month in the trailing window for the headline.
  const best = coreSsaTrend.reduce((b, m) => (m.score > b.score ? m : b));
  const isLastBest = best.month === last.month;

  const headline = isLastBest
    ? `${last.month} hit ${last.score} — best month in the trailing ${coreSsaTrend.length}. +${monthDelta} vs ${prev.month}, +${totalDelta} since ${first.month}.`
    : `${last.month} at ${last.score} · ${monthUp ? "+" : ""}${monthDelta} vs ${prev.month}. Best: ${best.month} (${best.score}).`;

  // Trailing-average target — anything below it is a "watch month".
  const trailingAvg = +(coreSsaTrend.reduce((a, m) => a + m.score, 0) / coreSsaTrend.length).toFixed(1);

  return (
    <SectionCard
      icon={<LineIcon size={13} />}
      title="Core SSA Average Trend"
      subtitle={headline}
      actions={
        <Link
          href="/ssa"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View Details
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* KPI strip — 3 micro-stats anchoring the chart. */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <TrendStat label="Latest" value={last.score.toFixed(1)} caption={last.month} tone="primary" />
        <TrendStat
          label="vs Prior"
          value={`${monthUp ? "+" : ""}${monthDelta}`}
          caption={prev.month}
          tone={monthUp ? "good" : "warn"}
          deltaIcon={monthUp ? "up" : "down"}
        />
        <TrendStat
          label={`Since ${first.month}`}
          value={`${totalDeltaUp ? "+" : ""}${totalDelta}`}
          caption={`${coreSsaTrend.length}-month trend`}
          tone={totalDeltaUp ? "good" : "warn"}
          deltaIcon={totalDeltaUp ? "up" : "down"}
        />
      </div>

      <div className="relative h-[230px] -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={coreSsaTrend} margin={{ top: 28, right: 12, bottom: 4, left: 0 }}>
            <defs>
              <linearGradient id="ssa-trend-area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="#3257d9" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#3257d9" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#eef2f4" strokeDasharray="0" vertical={false} />
            <YAxis
              domain={[0, 10]}
              ticks={[0, 2.5, 5, 7.5, 10]}
              tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
              width={28}
            />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: "var(--color-edify-muted)" }}
              axisLine={false}
              tickLine={false}
            />
            <Area
              type="monotone"
              dataKey="score"
              stroke="none"
              fill="url(#ssa-trend-area)"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="score"
              stroke="#3257d9"
              strokeWidth={2.5}
              dot={{ r: 4, fill: "#3257d9", strokeWidth: 2, stroke: "#ffffff" }}
              activeDot={{ r: 5 }}
            />
            <ReferenceDot
              x={last.month}
              y={last.score}
              r={5}
              fill="#3257d9"
              stroke="#ffffff"
              strokeWidth={2}
            />
          </ComposedChart>
        </ResponsiveContainer>

        {/* Highlight tooltip pinned over the last point */}
        <div className="absolute right-2 top-0 rounded-lg border border-[var(--color-edify-border)] bg-white shadow-md px-2 py-1.5 text-left">
          <div className="text-[10px] muted font-semibold leading-tight">
            {coreSsaTrendHighlight.monthLabel}
          </div>
          <div className="text-body-lg font-extrabold tabular leading-none mt-0.5">
            {coreSsaTrendHighlight.score}
          </div>
          <div className="text-[10px] text-emerald-600 font-semibold inline-flex items-center gap-0.5 leading-tight mt-0.5">
            <ArrowUpRight size={10} />
            {coreSsaTrendHighlight.delta} {coreSsaTrendHighlight.compareLabel}
          </div>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Target size={12} className="text-slate-500" />
          <span className="font-bold">Trailing avg:</span>
          <span className="muted">{trailingAvg} · keep months above this line.</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-emerald-600" />
          <span className="font-bold">Sustain the trend:</span>
          <span className="muted">push schools below 6.5 first — they pull the average down.</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── TrendStat ─────────────

type TrendTone = "primary" | "good" | "warn";

const TREND_TONE: Record<TrendTone, { bg: string; valueColor: string }> = {
  primary: { bg: "bg-gradient-to-br from-[var(--color-edify-soft)]/50 to-white border-[var(--color-edify-border)]", valueColor: "text-slate-900" },
  good:    { bg: "bg-gradient-to-br from-emerald-50 to-white border-emerald-200",                                   valueColor: "text-emerald-800" },
  warn:    { bg: "bg-gradient-to-br from-rose-50 to-white border-rose-200",                                          valueColor: "text-rose-800" },
};

function TrendStat({
  label,
  value,
  caption,
  tone,
  deltaIcon,
}: {
  label: string;
  value: string;
  caption: string;
  tone: TrendTone;
  deltaIcon?: "up" | "down";
}) {
  const p = TREND_TONE[tone];
  const Arrow = deltaIcon === "down" ? ArrowDownRight : ArrowUpRight;
  return (
    <div className={`rounded-xl border p-2.5 ${p.bg}`}>
      <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`text-[18px] font-extrabold tabular leading-none mt-1 inline-flex items-baseline gap-1 ${p.valueColor}`}>
        {deltaIcon && <Arrow size={12} className={tone === "good" ? "text-emerald-700" : tone === "warn" ? "text-rose-700" : ""} />}
        {value}
      </div>
      <div className="text-caption muted font-semibold mt-0.5 truncate">{caption}</div>
    </div>
  );
}
