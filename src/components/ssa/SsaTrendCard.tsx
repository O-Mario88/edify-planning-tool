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

// Two-line x-axis tick: "Q4" on top, "Jul–Sep '23" beneath. Splitting the
// quarter from its period (and shortening 2023 → '23) keeps eight labels from
// colliding without angling the text.
function QuarterTick({ x, y, payload }: { x?: number; y?: number; payload?: { value?: string | number } }) {
  const raw = String(payload?.value ?? "");
  const m = raw.match(/^(Q\d)\s*\(([^)]+)\)/);
  const quarter = m ? m[1] : raw;
  const period = (m ? m[2] : "").replace(/\b\d{2}(\d{2})\b/, "’$1"); // 2023 → ’23
  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <text x={0} y={0} dy={11} textAnchor="middle" fontSize={10.5} fontWeight={600} fill="#475569">{quarter}</text>
      <text x={0} y={0} dy={24} textAnchor="middle" fontSize={9} fill="#94a3b8">{period}</text>
    </g>
  );
}

export function SsaTrendCard() {
  return (
    <SectionCard
      icon={<TrendingUp size={13} />}
      title="SSA Performance Trend by Quarter"
      subtitle="Quarterly SSA average — track progress across recent quarters"
    >
      <div className="h-[236px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={ssaQuarterlyTrend} margin={{ top: 10, right: 16, left: 0, bottom: 6 }}>
            <CartesianGrid stroke="#eef2f4" vertical={false} />
            <XAxis
              dataKey="q"
              stroke="#647782"
              tickLine={false}
              axisLine={{ stroke: "#eef2f4" }}
              interval={0}
              height={34}
              tick={<QuarterTick />}
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
