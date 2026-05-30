"use client";

import { TrendingUp } from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  ReferenceLine,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { SectionCard } from "@/components/ui/primitives";
import { ssaQuarterlyTrend, ssaTrendTarget } from "@/lib/ssa-mock";

export function SsaTrendCard() {
  return (
    <SectionCard
      icon={<TrendingUp size={13} />}
      title="SSA Performance Trend by Quarter"
      subtitle="Quarterly SSA average — track progress across recent quarters"
    >
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={ssaQuarterlyTrend} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#eef2f4" vertical={false} />
            <XAxis
              dataKey="q"
              stroke="#647782"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: "#eef2f4" }}
              interval={0}
              dy={6}
            />
            <YAxis
              stroke="#647782"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              domain={[4, 8]}
              ticks={[4.0, 6.0, 8.0]}
              tickFormatter={(v: number) => v.toFixed(1)}
            />
            <Tooltip
              contentStyle={{ borderRadius: 10, border: "1px solid #d8e3e8", fontSize: 12 }}
              formatter={(value) => {
                const n = typeof value === "number" ? value : Number(value);
                return [n.toFixed(2), "SSA"];
              }}
            />
            <ReferenceLine
              y={ssaTrendTarget}
              stroke="#16a34a"
              strokeDasharray="6 4"
              strokeWidth={1.5}
              label={{ value: `Target (${ssaTrendTarget.toFixed(1)})`, position: "right", fill: "#16a34a", fontSize: 11, fontWeight: 600 }}
            />
            <Line
              dataKey="score"
              type="monotone"
              stroke="#16a34a"
              strokeWidth={2}
              dot={{ r: 3, fill: "#16a34a", stroke: "#fff", strokeWidth: 1 }}
              label={{
                position: "top",
                fontSize: 10,
                fill: "#0f1720",
                formatter: (label) => {
                  const n = typeof label === "number" ? label : Number(label);
                  return Number.isFinite(n) ? n.toFixed(2) : String(label ?? "");
                },
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="text-caption muted text-right mt-1">
        Quarterly average SSA score · Target line at 6.0
      </div>
    </SectionCard>
  );
}
