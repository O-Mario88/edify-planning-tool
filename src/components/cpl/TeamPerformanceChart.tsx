"use client";

import {
  BarChart3,
  ChevronDown,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import {
  ResponsiveContainer,
  ComposedChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Bar,
  Line,
  Legend,
} from "recharts";
import { teamPerformance } from "@/lib/cpl-mock";
import { SectionCard } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const PRIMARY = "#527083";
const PRIMARY_DARK = "#344f5f";
const ACCENT = "#f59e0b";
const PLANNED = "#cfe1e8";

export function TeamPerformanceOverviewChart() {
  // Compute the headline KPIs from the last two data points so the
  // strip + takeaway always match whatever the mock returns. Real
  // backend swaps `teamPerformance` for a server query — the strip
  // logic stays the same.
  const last = teamPerformance.at(-1)!;
  const prev = teamPerformance.at(-2)!;

  const deltaPlanned   = last.planned   - prev.planned;
  const deltaCompleted = last.completed - prev.completed;
  const deltaVerified  = last.verified  - prev.verified;
  const deltaTarget    = last.targetPct - prev.targetPct;

  const completionRate    = Math.round((last.completed / last.planned) * 100);
  const verificationRate  = Math.round((last.verified  / last.completed) * 100);

  // The chart's editorial headline. Identifies the most-defensible
  // claim from the data so the CPL reads insight first, chart second.
  const bestMonth = teamPerformance.reduce((best, m) => (m.targetPct > best.targetPct ? m : best));
  const isLastBest = bestMonth.month === last.month;
  const headline = isLastBest
    ? `${last.month.split(" ")[0]} is the strongest month in the trailing year — ${last.targetPct}% target achievement.`
    : `${last.month.split(" ")[0]} hit ${last.targetPct}% — ${bestMonth.month.split(" ")[0]} still leads the trailing year at ${bestMonth.targetPct}%.`;

  // Below-chart takeaway — verification quality. Anything below 90%
  // verification flips this to a warning so the CPL knows the gap.
  const verifyGood = verificationRate >= 90;
  const takeaway = verifyGood
    ? `Verified-to-completed at ${verificationRate}% — above the 90% quality bar. Pipeline is healthy.`
    : `Verified-to-completed at ${verificationRate}% — below the 90% quality bar. Push verification before adding more activities.`;

  return (
    <SectionCard
      icon={<BarChart3 size={13} />}
      title="Team Performance Overview"
      subtitle={headline}
      actions={
        <button
          type="button"
          className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white flex items-center gap-1.5 text-[12px] font-semibold"
        >
          Last 12 Months
          <ChevronDown size={11} className="text-[var(--color-edify-muted)]" />
        </button>
      }
    >
      {/* KPI strip — 4 tiles answering "what is this month's number,
          how does it compare, and is the ratio healthy?" */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <KpiTile
          label="Planned"
          value={last.planned}
          delta={deltaPlanned}
          deltaSuffix=" vs prior"
          caption="Activities scheduled this month"
          tone="neutral"
          stagger="stagger-1"
        />
        <KpiTile
          label="Completed"
          value={last.completed}
          delta={deltaCompleted}
          deltaSuffix=" vs prior"
          caption={`${completionRate}% of planned`}
          tone="primary"
          metaIcon={TrendingUp}
          stagger="stagger-2"
        />
        <KpiTile
          label="Verified"
          value={last.verified}
          delta={deltaVerified}
          deltaSuffix=" vs prior"
          caption={`${verificationRate}% of completed`}
          tone="primary-dark"
          metaIcon={ShieldCheck}
          metaTone={verifyGood ? "good" : "warn"}
          stagger="stagger-3"
        />
        <KpiTile
          label="Target Achievement"
          value={last.targetPct}
          valueSuffix="%"
          delta={deltaTarget}
          deltaSuffix=" pp vs prior"
          caption={isLastBest ? "Best month — trailing year" : `Best: ${bestMonth.targetPct}% in ${bestMonth.month.split(" ")[0]}`}
          tone="accent"
          stagger="stagger-4"
        />
      </div>

      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={teamPerformance} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#eef2f4" vertical={false} />
            <XAxis
              dataKey="month"
              stroke="#647782"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: "#eef2f4" }}
              tickFormatter={(m: string) => m.replace(" 20", " ")}
            />
            <YAxis
              yAxisId="left"
              stroke="#647782"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `${v / 1000}K`}
              ticks={[0, 20000, 40000, 60000, 80000]}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="#647782"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              cursor={{ fill: "rgba(82,112,131,0.06)" }}
              contentStyle={{
                borderRadius: 10,
                border: "1px solid #d8e3e8",
                fontSize: 12,
                fontFamily: "inherit",
              }}
              labelStyle={{ fontWeight: 700, color: "#0f1720" }}
              formatter={(value, name) => {
                const v = typeof value === "number" ? value : Number(value);
                const key = String(name);
                return key === "targetPct"
                  ? [`${v}%`, "Target Achievement %"]
                  : [v.toLocaleString(), legendName(key)];
              }}
            />
            <Legend
              verticalAlign="top"
              height={28}
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 11, color: "#647782" }}
              formatter={(v) => legendName(v)}
            />
            <Bar yAxisId="left" dataKey="planned"   name="Planned Activities"    fill={PLANNED}      radius={[3, 3, 0, 0]} barSize={12} />
            <Bar yAxisId="left" dataKey="completed" name="Completed Activities"  fill={PRIMARY}      radius={[3, 3, 0, 0]} barSize={12} />
            <Bar yAxisId="left" dataKey="verified"  name="Verified Activities"   fill={PRIMARY_DARK} radius={[3, 3, 0, 0]} barSize={12} />
            <Line
              yAxisId="right"
              dataKey="targetPct"
              name="Target Achievement %"
              stroke={ACCENT}
              strokeWidth={2}
              dot={{ r: 3, fill: ACCENT, stroke: "#fff", strokeWidth: 1 }}
              activeDot={{ r: 5 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Takeaway — the one sentence the CPL should walk away with.
          Tone shifts to amber when verification falls below the 90%
          quality bar. */}
      <div
        className={cn(
          "mt-3 pt-3 border-t border-[#eef2f4] flex items-start gap-2 text-[13px] leading-snug",
          verifyGood ? "text-emerald-700" : "text-amber-700",
        )}
      >
        <ShieldCheck size={14} className="mt-[2px] shrink-0" />
        <span className="font-semibold">{takeaway}</span>
      </div>
    </SectionCard>
  );
}

function legendName(key: string) {
  if (key === "planned") return "Planned Activities";
  if (key === "completed") return "Completed Activities";
  if (key === "verified") return "Verified Activities";
  if (key === "targetPct") return "Target Achievement %";
  return key;
}

// ───────────── KpiTile ─────────────

type Tone = "neutral" | "primary" | "primary-dark" | "accent";

const TONE_CHIP: Record<Tone, string> = {
  neutral:        "bg-slate-50 border-slate-200",
  primary:        "bg-[#eaf2f6] border-[#cfe1e8]",
  "primary-dark": "bg-[#dfeaef] border-[#bcd1da]",
  accent:         "bg-amber-50 border-amber-200",
};

const TONE_DOT: Record<Tone, string> = {
  neutral:        "bg-slate-300",
  primary:        "bg-[#527083]",
  "primary-dark": "bg-[#344f5f]",
  accent:         "bg-amber-500",
};

function KpiTile({
  label,
  value,
  valueSuffix,
  delta,
  deltaSuffix = "",
  caption,
  tone,
  metaIcon,
  metaTone,
  stagger,
}: {
  label: string;
  value: number;
  valueSuffix?: string;
  delta: number;
  deltaSuffix?: string;
  caption: string;
  tone: Tone;
  metaIcon?: LucideIcon;
  metaTone?: "good" | "warn";
  stagger?: string;
}) {
  const up = delta >= 0;
  const Arrow = up ? ArrowUpRight : ArrowDownRight;
  const MetaIcon = metaIcon;
  const metaClass =
    metaTone === "warn"
      ? "text-amber-700"
      : metaTone === "good"
        ? "text-emerald-700"
        : "muted";
  return (
    <div className={cn("rounded-xl border p-3 flex flex-col gap-1.5 card-lift cursor-default tile-in", stagger, TONE_CHIP[tone])}>
      <div className="flex items-center gap-1.5">
        <span className={cn("w-1.5 h-1.5 rounded-full", TONE_DOT[tone])} />
        <span className="text-caption font-semibold uppercase tracking-wide text-slate-600">
          {label}
        </span>
      </div>
      <div className="text-[20px] font-extrabold tabular leading-none">
        {value.toLocaleString()}{valueSuffix ?? ""}
      </div>
      <div
        className={cn(
          "inline-flex items-center gap-0.5 text-caption font-bold w-fit",
          up ? "text-emerald-700" : "text-rose-700",
        )}
      >
        <Arrow size={11} />
        {up ? "+" : ""}{Math.abs(delta).toLocaleString()}{deltaSuffix}
      </div>
      <div className={cn("text-caption font-semibold leading-tight inline-flex items-center gap-1", metaClass)}>
        {MetaIcon && <MetaIcon size={11} className="shrink-0" />}
        <span className="truncate">{caption}</span>
      </div>
    </div>
  );
}
