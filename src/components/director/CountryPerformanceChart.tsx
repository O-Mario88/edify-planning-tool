"use client";

import { useState } from "react";
import {
  BarChart3,
  Activity,
  ChevronDown,
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
import { monthlyPerformance } from "@/lib/director-mock";
import { SectionCard } from "@/components/ui/primitives";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const PRIMARY = "#527083";
const PRIMARY_DARK = "#344f5f";
const ACCENT = "#f59e0b";
const PLANNED = "#cfe1e8";

export function CountryPerformanceChart() {
  const [range] = useState("Last 11 Months");

  if (!isMockAllowed()) {
    return (
      <SectionCard icon={<BarChart3 size={13} />} title="Country Performance Overview">
        <InsufficientData surface="the country performance trend chart" />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      icon={<BarChart3 size={13} />}
      title="Country Performance Overview"
      subtitle={undefined}
      actions={
        <button
          type="button"
          className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white flex items-center gap-1.5 text-[12px] font-semibold"
        >
          {range}
          <ChevronDown size={11} className="text-[var(--color-edify-muted)]" />
        </button>
      }
    >
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={monthlyPerformance} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
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
            <Bar yAxisId="left" dataKey="planned"   name="Planned Activities"    fill={PLANNED}      radius={[3, 3, 0, 0]} barSize={14} />
            <Bar yAxisId="left" dataKey="completed" name="Completed Activities"  fill={PRIMARY}      radius={[3, 3, 0, 0]} barSize={14} />
            <Bar yAxisId="left" dataKey="verified"  name="Verified Activities"   fill={PRIMARY_DARK} radius={[3, 3, 0, 0]} barSize={14} />
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

// ─────── Regional ranking card ───────

import { regionalPerformance, nationalAverageAchievement } from "@/lib/director-mock";

export function RegionalPerformanceCard() {
  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="Regional Performance"
      actions={
        <button
          type="button"
          className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white flex items-center gap-1.5 text-[12px] font-semibold"
        >
          Target Achievement %
          <ChevronDown size={11} className="text-[var(--color-edify-muted)]" />
        </button>
      }
    >
      <div className="grid grid-cols-[28px_1fr_56px] gap-x-2 gap-y-2 items-center text-[12px]">
        <div className="muted text-caption uppercase font-semibold">Rank</div>
        <div className="muted text-caption uppercase font-semibold">Region</div>
        <div className="muted text-caption uppercase font-semibold text-right">Achievement</div>

        {regionalPerformance.map((r) => {
          const tone =
            r.achievementPct >= 75
              ? "var(--color-success)"
              : r.achievementPct >= 60
                ? "var(--color-edify-orange)"
                : "var(--color-danger)";
          return (
            <RegionalRow
              key={r.region}
              rank={r.rank}
              region={r.region}
              pct={r.achievementPct}
              tone={tone}
            />
          );
        })}
      </div>

      <div className="mt-4 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[12px]">
        <div className="font-bold">National Average</div>
        <div className="flex items-center gap-2 flex-1 max-w-[60%]">
          <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${nationalAverageAchievement}%`, background: "var(--color-edify-primary)" }}
            />
          </div>
        </div>
        <div className="text-body font-extrabold tabular w-[56px] text-right">
          {nationalAverageAchievement}%
        </div>
      </div>
    </SectionCard>
  );
}

function RegionalRow({
  rank,
  region,
  pct,
  tone,
}: {
  rank: number;
  region: string;
  pct: number;
  tone: string;
}) {
  return (
    <>
      <div className="font-bold tabular">{rank}</div>
      <div className="font-semibold">{region}</div>
      <div className="text-right tabular text-body font-bold">{pct}%</div>
      <div className="col-start-2 col-span-2 -mt-1 mb-1">
        <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
        </div>
      </div>
    </>
  );
}
