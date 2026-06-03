"use client";

// Budget chart vocabulary (recharts) for the budget dashboards. Fed live data
// from the annual rollup. Mirrors the analytics/field-engine chart style.

import { type ComponentProps } from "react";
import {
  ResponsiveContainer, BarChart, Bar, ComposedChart, Line, LineChart, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, LabelList,
} from "recharts";
import { fmtUgxShort } from "@/lib/funds/budget/budget-format";
import type { AmountBreakdown } from "@/lib/funds/budget/annual-rollup";

// recharts v3 formatter props are strict intersection types — cast like the
// analytics charts do.
type TipFmt = ComponentProps<typeof Tooltip>["formatter"];
type LblFmt = ComponentProps<typeof LabelList>["formatter"];
const moneyTip = ((v: number) => fmtUgxShort(Number(v))) as TipFmt;
const moneyLabel = ((v: number) => fmtUgxShort(Number(v))) as LblFmt;

const GREEN = "#1f4d3a";
const ORANGE = "#ea8c2f";
const BLUE = "#2f6fed";
const PURPLE = "#7c5cff";
const LIGHT = "#9ec1cf";
const axis = { fontSize: 11, fill: "#64748b" };

export function BudgetByQuarterBars({ data, height = 260 }: {
  data: { quarter: string; approved: number; requested: number; released: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef2f4" />
        <XAxis dataKey="quarter" tick={axis} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={fmtUgxShort} tick={axis} axisLine={false} tickLine={false} width={56} />
        <Tooltip formatter={moneyTip} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="approved" name="Approved Budget" fill={GREEN} radius={[3, 3, 0, 0]} />
        <Bar dataKey="requested" name="Requested Funds" fill={ORANGE} radius={[3, 3, 0, 0]} />
        <Bar dataKey="released" name="Released Funds" fill={BLUE} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function MonthlyBurnReleases({ data, height = 260 }: {
  data: { label: string; released: number; spent: number; runRate: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef2f4" />
        <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={fmtUgxShort} tick={axis} axisLine={false} tickLine={false} width={56} />
        <Tooltip formatter={moneyTip} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="released" name="Released Funds" fill={BLUE} radius={[3, 3, 0, 0]} />
        <Line dataKey="spent" name="Spent (Burn)" stroke={ORANGE} strokeWidth={2} dot={{ r: 2 }} />
        <Line dataKey="runRate" name="Budgeted Run Rate" stroke={GREEN} strokeWidth={2} strokeDasharray="5 4" dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function BudgetByDimensionBars({ data, height = 280, color = GREEN }: {
  data: AmountBreakdown; height?: number; color?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#eef2f4" />
        <XAxis type="number" tickFormatter={fmtUgxShort} tick={axis} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="label" tick={{ fontSize: 11, fill: "#334155" }} axisLine={false} tickLine={false} width={104} />
        <Tooltip formatter={moneyTip} />
        <Bar dataKey="amount" name="Approved Budget" fill={color} radius={[0, 3, 3, 0]}>
          <LabelList dataKey="amount" position="right" formatter={moneyLabel} style={{ fontSize: 10, fill: "#475569" }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ProgramAdminDonut({ program, admin, centerPct, centerLabel }: {
  program: number; admin: number; centerPct: string; centerLabel: string;
}) {
  const data = [
    { name: "Program Cost", value: program, color: GREEN },
    { name: "Admin Cost", value: admin, color: ORANGE },
  ];
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={62} outerRadius={92} paddingAngle={2} startAngle={90} endAngle={-270}>
            {data.map((d) => <Cell key={d.name} fill={d.color} />)}
          </Pie>
          <Tooltip formatter={moneyTip} />
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 grid place-items-center pointer-events-none" style={{ bottom: 0 }}>
        <div className="text-center -mt-1">
          <div className="text-[20px] font-extrabold tabular">{centerPct}</div>
          <div className="text-[10px] muted">{centerLabel}</div>
        </div>
      </div>
    </div>
  );
}

export function BudgetMixDonut({ data, centerPct, centerLabel }: {
  data: AmountBreakdown; centerPct: string; centerLabel: string;
}) {
  const palette = [GREEN, BLUE, PURPLE, ORANGE, LIGHT];
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} dataKey="amount" nameKey="label" innerRadius={62} outerRadius={92} paddingAngle={2} startAngle={90} endAngle={-270}>
            {data.map((d, i) => <Cell key={d.key} fill={palette[i % palette.length]} />)}
          </Pie>
          <Tooltip formatter={moneyTip} />
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 grid place-items-center pointer-events-none">
        <div className="text-center">
          <div className="text-[20px] font-extrabold tabular">{centerPct}</div>
          <div className="text-[10px] muted">{centerLabel}</div>
        </div>
      </div>
    </div>
  );
}

export function AnnualOverviewLines({ data, height = 300 }: {
  data: { label: string; approved: number; requested: number; released: number; remaining: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef2f4" />
        <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={fmtUgxShort} tick={axis} axisLine={false} tickLine={false} width={56} />
        <Tooltip formatter={moneyTip} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line dataKey="approved" name="Approved Budget" stroke={GREEN} strokeWidth={2} dot={false} />
        <Line dataKey="requested" name="Requested Funds" stroke={BLUE} strokeWidth={2} dot={false} />
        <Line dataKey="released" name="Released Funds" stroke={PURPLE} strokeWidth={2} dot={false} />
        <Line dataKey="remaining" name="Remaining Balance" stroke="#5cba7d" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
