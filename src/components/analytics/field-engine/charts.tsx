"use client";

// Premium chart vocabulary for the engine-backed analytics surface.
//
// Every chart here is fed live data from the AnalyticsSnapshot — nothing is
// invented. The components are deliberately presentational (no data fetching,
// no filter state) so the dashboard can compose them into an organized grid.
// Palette + tooltip styling are shared so the whole surface reads as one
// coherent, data-room-grade analytics product.

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  LabelList,
} from "recharts";
import type { ComponentProps } from "react";
import type { FunnelStage, HeatmapRow } from "@/lib/analytics/types";

// recharts v3's Tooltip `formatter` is a strict intersection type; a single
// alias keeps the call sites readable while satisfying it.
type TooltipFormatter = ComponentProps<typeof Tooltip>["formatter"];

// ── Shared palette (Edify deep-teal family + signal colours) ──
export const C = {
  primary: "#073f4a",
  deep: "#0a4856",
  teal: "#3a7d8c",
  steel: "#527083",
  mist: "#cfe1e8",
  accent: "#f59e0b",
  success: "#0f8a5f",
  successSoft: "#a7f3d0",
  danger: "#d93b50",
  grid: "#eef2f4",
  axis: "#647782",
};

const tooltipStyle = {
  borderRadius: 12,
  border: "1px solid #d8e3e8",
  boxShadow: "0 8px 24px rgba(7,63,74,.12)",
  fontSize: 12,
  fontFamily: "inherit",
  padding: "8px 10px",
} as const;

const tooltipLabelStyle = { fontWeight: 700, color: "#0f1720", marginBottom: 2 } as const;

function ChartFrame({ height, children }: { height: number; children: React.ReactElement }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

function ChartEmpty({ height, label }: { height: number; label: string }) {
  return (
    <div
      style={{ height }}
      className="grid place-items-center rounded-xl border border-dashed border-[var(--color-edify-border)] bg-[var(--surface-2)]"
    >
      <span className="t-caption muted">{label}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Momentum — completed activities by month (area + line)
// ─────────────────────────────────────────────────────────────

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function monthLabel(period: string): string {
  const m = Number(period.slice(5, 7));
  return Number.isFinite(m) && m >= 1 && m <= 12 ? MONTHS[m - 1] : period;
}

export function MomentumChart({ data, height = 260 }: { data: { period: string; value: number }[]; height?: number }) {
  if (data.length === 0) return <ChartEmpty height={height} label="No completed activity in this period yet." />;
  const rows = data.map((d) => ({ ...d, label: monthLabel(d.period) }));
  return (
    <ChartFrame height={height}>
      <AreaChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id="momentumFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.primary} stopOpacity={0.28} />
            <stop offset="100%" stopColor={C.primary} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={C.grid} vertical={false} />
        <XAxis dataKey="label" stroke={C.axis} fontSize={11} tickLine={false} axisLine={{ stroke: C.grid }} />
        <YAxis stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={36} />
        <Tooltip
          cursor={{ stroke: C.teal, strokeWidth: 1, strokeDasharray: "4 4" }}
          contentStyle={tooltipStyle}
          labelStyle={tooltipLabelStyle}
          formatter={((v) => `${Number(v).toLocaleString()} completed`) as TooltipFormatter}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={C.primary}
          strokeWidth={2.4}
          fill="url(#momentumFill)"
          dot={{ r: 3, fill: C.primary, stroke: "#fff", strokeWidth: 1.5 }}
          activeDot={{ r: 5, fill: C.accent, stroke: "#fff", strokeWidth: 2 }}
        />
      </AreaChart>
    </ChartFrame>
  );
}

// ─────────────────────────────────────────────────────────────
// Pipeline funnel — planned → completed → verified → paid
// (SVG/CSS funnel with stage-to-stage conversion rates)
// ─────────────────────────────────────────────────────────────

const STAGE_TONE = [C.mist, C.teal, C.deep, C.primary];

export function PipelineFunnel({ stages, height }: { stages: FunnelStage[]; height?: number }) {
  const max = Math.max(1, ...stages.map((s) => s.count));
  void height;
  return (
    <div className="space-y-2.5">
      {stages.map((s, i) => {
        const pct = Math.max(4, (s.count / max) * 100);
        const prev = i > 0 ? stages[i - 1].count : null;
        const conv = prev && prev > 0 ? Math.round((s.count / prev) * 100) : null;
        return (
          <div key={s.key} className="flex items-center gap-3">
            <div className="w-[88px] shrink-0">
              <div className="t-caption font-bold leading-tight">{s.label}</div>
              {conv !== null && (
                <div className="t-tiny muted tabular">{conv}% of prev</div>
              )}
            </div>
            <div className="flex-1 h-9 rounded-lg bg-[var(--surface-2)] overflow-hidden">
              <div
                className="h-full rounded-lg flex items-center justify-end pr-2.5 transition-[width] duration-500"
                style={{ width: `${pct}%`, background: STAGE_TONE[i] ?? C.primary }}
              >
                <span className={"t-caption font-extrabold tabular " + (i >= 2 ? "text-white" : "text-[var(--color-edify-primary)]")}>
                  {s.count.toLocaleString()}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Verification donut — where reached schools sit in the evidence funnel
// ─────────────────────────────────────────────────────────────

export function VerificationDonut({
  breakdown,
  height = 200,
}: {
  breakdown: { planned: number; completed: number; verified: number; donorReady: number };
  height?: number;
}) {
  const total = breakdown.planned;
  const donor = breakdown.donorReady;
  const verifiedOnly = Math.max(0, breakdown.verified - breakdown.donorReady);
  const completedOnly = Math.max(0, breakdown.completed - breakdown.verified);
  const reachedOnly = Math.max(0, breakdown.planned - breakdown.completed);
  const slices = [
    { name: "Donor-ready", value: donor, color: C.success },
    { name: "IA-verified", value: verifiedOnly, color: C.deep },
    { name: "Completed", value: completedOnly, color: C.teal },
    { name: "Reached only", value: reachedOnly, color: C.mist },
  ].filter((s) => s.value > 0);

  if (total === 0) return <ChartEmpty height={height} label="No reached schools in scope." />;
  const verifiedPct = total > 0 ? Math.round((breakdown.verified / total) * 100) : 0;

  return (
    <div className="flex items-center gap-3">
      <div className="relative shrink-0" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="92%"
              paddingAngle={2}
              startAngle={90}
              endAngle={-270}
              stroke="none"
            >
              {slices.map((s) => (
                <Cell key={s.name} fill={s.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={((v) => `${Number(v).toLocaleString()} schools`) as TooltipFormatter}
            />
          </PieChart>
        </ResponsiveContainer>
        {/* Center label scales with the donut so it always fits the inner hole. */}
        <div className="absolute inset-0 flex flex-col items-center justify-center leading-none pointer-events-none px-2 text-center">
          <div className="num-hero font-extrabold tabular" style={{ fontSize: Math.max(15, Math.round(height * 0.15)) }}>{verifiedPct}%</div>
          <div className="muted" style={{ fontSize: Math.max(9, Math.round(height * 0.05)), marginTop: 2 }}>IA-verified</div>
        </div>
      </div>
      <ul className="flex-1 min-w-0 space-y-1.5">
        {slices.map((s) => (
          <li key={s.name} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: s.color }} />
            <span className="t-caption font-semibold flex-1 truncate">{s.name}</span>
            <span className="t-caption font-bold tabular">{s.value.toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SSA intervention ranking — average score per intervention (bar)
// ─────────────────────────────────────────────────────────────

function ssaBarColor(score: number): string {
  if (score >= 9) return C.success;
  if (score >= 7) return "#34a06f";
  if (score >= 5) return C.accent;
  return C.danger;
}

export function InterventionRankBar({
  interventions,
  rows,
  height = 260,
}: {
  interventions: string[];
  rows: HeatmapRow[];
  height?: number;
}) {
  const data = interventions
    .map((a) => {
      let sum = 0;
      let n = 0;
      for (const row of rows) {
        const v = row.scores[a];
        if (typeof v === "number") {
          sum += v;
          n += 1;
        }
      }
      return { name: a, value: n > 0 ? Math.round((sum / n) * 10) / 10 : null };
    })
    .filter((d): d is { name: string; value: number } => d.value !== null)
    .sort((x, y) => y.value - x.value);

  if (data.length === 0) return <ChartEmpty height={height} label="No SSA scores for reached schools yet." />;

  return (
    <ChartFrame height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 28, left: 4, bottom: 0 }} barCategoryGap={6}>
        <CartesianGrid stroke={C.grid} horizontal={false} />
        <XAxis type="number" domain={[0, 10]} stroke={C.axis} fontSize={11} tickLine={false} axisLine={{ stroke: C.grid }} ticks={[0, 2, 4, 6, 8, 10]} />
        <YAxis type="category" dataKey="name" width={132} stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} interval={0} />
        <Tooltip
          cursor={{ fill: "rgba(82,112,131,.06)" }}
          contentStyle={tooltipStyle}
          formatter={((v) => `${v} / 10 avg`) as TooltipFormatter}
        />
        <Bar dataKey="value" radius={[0, 5, 5, 0]} barSize={16}>
          {data.map((d) => (
            <Cell key={d.name} fill={ssaBarColor(d.value)} />
          ))}
          <LabelList dataKey="value" position="right" fontSize={11} fontWeight={700} fill={C.axis} />
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}

// ─────────────────────────────────────────────────────────────
// SSA heatmap — district × intervention matrix (premium grid)
// ─────────────────────────────────────────────────────────────

function cellTone(score: number | undefined): { bg: string; fg: string } {
  if (score === undefined) return { bg: "var(--surface-2)", fg: "var(--text-muted)" };
  if (score >= 9) return { bg: "#0f8a5f", fg: "#ffffff" };
  if (score >= 7) return { bg: "#a7f3d0", fg: "#065f46" };
  if (score >= 5) return { bg: "#fde68a", fg: "#78350f" };
  return { bg: "#fecaca", fg: "#991b1b" };
}

const HEAT_LEGEND = [
  { label: "0–4 Critical", bg: "#fecaca", fg: "#991b1b" },
  { label: "5–6 Needs support", bg: "#fde68a", fg: "#78350f" },
  { label: "7–8 Good", bg: "#a7f3d0", fg: "#065f46" },
  { label: "9–10 Strong", bg: "#0f8a5f", fg: "#ffffff" },
];

export function SsaHeatmap({ interventions, rows }: { interventions: string[]; rows: HeatmapRow[] }) {
  if (rows.length === 0) return <ChartEmpty height={120} label="No district SSA data for reached schools yet." />;
  return (
    <div>
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full border-separate" style={{ borderSpacing: "3px" }}>
          <thead>
            <tr>
              <th className="t-tiny uppercase tracking-wide muted font-bold text-left pr-2 align-bottom pb-1">District</th>
              {interventions.map((a) => (
                <th
                  key={a}
                  className="t-tiny muted font-semibold align-bottom pb-1"
                  style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", height: 96, whiteSpace: "nowrap" }}
                >
                  {a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="t-caption font-semibold pr-2 whitespace-nowrap">{row.label}</td>
                {interventions.map((a) => {
                  const v = row.scores[a];
                  const tone = cellTone(v);
                  return (
                    <td key={a} className="p-0">
                      <div
                        title={`${row.label} · ${a}: ${v ?? "no data"}`}
                        className="grid place-items-center h-9 min-w-[34px] rounded-md t-caption font-extrabold tabular"
                        style={{ backgroundColor: tone.bg, color: tone.fg }}
                      >
                        {v ?? "—"}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {HEAT_LEGEND.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm shrink-0" style={{ background: l.bg }} />
            <span className="t-tiny muted font-semibold">{l.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
