"use client";

import { useMemo } from "react";
import {
  ChevronRight,
  Info,
  Building2,
  GraduationCap,
  Activity,
  CheckCircle2,
  ClipboardCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  PERIODS,
  computeRow,
  type ComputedRow,
  type MetricIconKey,
  type OperatingTargets,
  type PeriodKey,
  type Status,
} from "@/lib/operating-targets-mock";
import Link from "next/link";
import { quarterLabel, MID_YEAR_MONTH_RANGE } from "@/lib/fy/fy-core";
import { HealthPill } from "@/components/ui/Pill";
import { ExportButton } from "@/components/ui/ExportButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { MetricStrip } from "@/components/ui/MetricStrip";
import type { FilterScope } from "@/lib/filters/types";
import { cn } from "@/lib/utils";

// Resolve the icon key (a plain string carried across the
// server→client boundary) to a Lucide component on the client.
const METRIC_ICON: Record<MetricIconKey, LucideIcon> = {
  building2:      Building2,
  graduationCap:  GraduationCap,
  activity:       Activity,
  checkCircle2:   CheckCircle2,
  clipboardCheck: ClipboardCheck,
  wallet:         Wallet,
};

// ────────── Status palette ──────────

const STATUS_TEXT: Record<Status, string> = {
  "On Track":     "text-emerald-700",
  "At Risk":      "text-amber-700",
  "Off Track":    "text-rose-700",
  "Not Started":  "text-slate-500",
};
const STATUS_RING: Record<Status, string> = {
  "On Track":     "#10b981",
  "At Risk":      "#f59e0b",
  "Off Track":    "#ef4444",
  "Not Started":  "#cbd5e1",
};
// Status pills now flow through the shared <HealthPill> primitive in
// src/components/ui/Pill.tsx — kept here as a name-only reference for
// any downstream code still importing the old constant.

// ────────── Donut (period tiles + perf distribution) ──────────

function Donut({
  pct,
  size = 56,
  stroke = 7,
  color,
}: {
  pct: number;
  size?: number;
  stroke?: number;
  color: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = (Math.min(pct, 100) / 100) * c;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-edify-divider)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${dash} ${c - dash}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
  );
}

// ────────── Main view ──────────

export function OperatingTargetsView({ data }: { data: OperatingTargets }) {
  // Pre-compute every row's per-period cells; same calc the table and
  // the top tiles both read so they can never drift.
  const rows = useMemo(
    () => data.metrics.map((m) => computeRow(m, data.startedPeriods)),
    [data.metrics, data.startedPeriods],
  );

  // Aggregate %s per period across all metric rows (weighted by target
  // so a row with bigger volume doesn't get overwhelmed by a tiny one).
  const periodAgg = useMemo(() => {
    const out: Record<PeriodKey, { target: number; achieved: number; pct: number; status: Status }> = {} as Record<
      PeriodKey,
      { target: number; achieved: number; pct: number; status: Status }
    >;
    for (const p of PERIODS) {
      const target = rows.reduce((s, r) => s + r.cells[p.key].target, 0);
      const achieved = rows.reduce((s, r) => s + r.cells[p.key].achieved, 0);
      const pct = target > 0 ? Math.round((achieved / target) * 100) : 0;
      const started = data.startedPeriods[p.key];
      const status: Status = !started ? "Not Started" : pct >= 70 ? "On Track" : pct >= 50 ? "At Risk" : "Off Track";
      out[p.key] = { target, achieved, pct, status };
    }
    return out;
  }, [rows, data.startedPeriods]);

  const distribution = useMemo(() => {
    let onTrack = 0, atRisk = 0, offTrack = 0;
    for (const r of rows) {
      const c = r.cells.q2; // "active" quarter — matches the design call-out
      if (c.status === "On Track") onTrack++;
      else if (c.status === "At Risk") atRisk++;
      else if (c.status === "Off Track") offTrack++;
    }
    const total = onTrack + atRisk + offTrack;
    return { onTrack, atRisk, offTrack, total };
  }, [rows]);

  return (
    <div className="space-y-4">
      {/* PageHeader is rendered by the route (above the welcome hero) via
          <OperatingTargetsPageHeader />. The view body starts directly
          with the period donut tiles so there's no duplicate header
          strip mid-page. */}

      {/* Period donut tiles row */}
      <section>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
          {PERIODS.map((p, i) => {
            const baseCell = periodAgg[p.key];
            // The Monthly tile shows calendar progress (days completed)
            // rather than metric-aggregate %, because mid-month it's the
            // more honest read of "how far through this period are you".
            const c = p.key === "monthly"
              ? {
                  achieved: data.daysCompleted.done,
                  target:   data.daysCompleted.total,
                  pct:      Math.round((data.daysCompleted.done / Math.max(1, data.daysCompleted.total)) * 100),
                  status:   baseCell.status,
                }
              : baseCell;
            const cellTone = p.key === "monthly" ? { primary: "#3b82f6" } : { primary: STATUS_RING[c.status] };
            const subStat = p.key === "monthly"
              ? `${data.daysCompleted.done} / ${data.daysCompleted.total}`
              : `${c.achieved.toLocaleString()} / ${c.target.toLocaleString()}`;
            const subLabel = p.key === "monthly" ? "Days Completed" : "Achieved";
            return (
              <div key={p.key} className="relative">
                <div
                  className={cn(
                    "card rounded-2xl p-3 h-full flex flex-col gap-2",
                    p.band,
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="t-caption font-extrabold tracking-tight">{p.label}</div>
                      <div className={cn("t-tiny font-bold uppercase tracking-[0.07em] mt-0.5", p.tone)}>{p.sub}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <div className="relative shrink-0">
                      <Donut pct={c.pct} color={cellTone.primary} />
                      <div className="absolute inset-0 grid place-items-center">
                        <span className="t-body font-extrabold text-[var(--color-edify-text)]">{c.pct}%</span>
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className={cn("t-caption font-extrabold", STATUS_TEXT[c.status])}>{c.status}</div>
                      <div className="t-caption text-muted mt-0.5 truncate">{subLabel}</div>
                    </div>
                  </div>
                  <div className="t-body font-bold mt-auto tabular">{subStat}</div>
                </div>
                {i < PERIODS.length - 1 && (
                  <ChevronRight
                    size={14}
                    className="hidden lg:block absolute -right-2.5 top-1/2 -translate-y-1/2 text-disabled z-10"
                  />
                )}
              </div>
            );
          })}
        </div>
        <div className="flex items-center justify-between mt-2 px-1">
          <p className="t-caption muted">
            Monthly achievements contribute to <span className="font-semibold">Quarterly</span>, <span className="font-semibold">Mid Year</span>, and <span className="font-semibold">Full Year</span> totals.
          </p>
          <button className="t-caption font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1">
            <Info size={11} /> How roll-up works
          </button>
        </div>
      </section>

      {/* KPI summary row — full-year achievement vs target as a dense metric
          strip (replaces the big tiles + their decorative sparklines). */}
      <MetricStrip
        columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6"
        metrics={rows.map((r) => {
          const c = r.cells.fy;
          return {
            key: r.key,
            label: r.label,
            value: c.achieved.toLocaleString(),
            unit: `/ ${c.target.toLocaleString()}`,
            caption: `${c.pct}% of Target`,
            icon: METRIC_ICON[r.iconKey],
          };
        })}
      />

      {/* Targets by Time Period — table */}
      <section className="card rounded-2xl overflow-hidden">
        <header className="px-4 py-3.5 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-3">
          <h2 className="t-body-lg font-extrabold tracking-tight">Targets by Time Period</h2>
        </header>
        <div className="overflow-x-auto">
          <table className="min-w-[1160px] w-full t-caption">
            <thead className="bg-[var(--color-edify-soft)]/40">
              <tr>
                <th className="text-left px-4 py-2 w-[180px]">
                  <div className="t-tiny font-bold uppercase tracking-[0.07em] muted">Target Area</div>
                </th>
                {PERIODS.map((p) => (
                  <th key={p.key} className={cn("px-3 py-2 text-center border-l border-[var(--color-edify-divider)]", p.band)}>
                    <div className="t-caption font-extrabold tracking-tight">{p.label}</div>
                    <div className={cn("t-tiny font-bold uppercase tracking-[0.07em] mt-0.5", p.tone)}>{p.sub}</div>
                  </th>
                ))}
              </tr>
              <tr className="bg-[var(--color-edify-soft)]/20">
                <th></th>
                {PERIODS.map((p) => (
                  <th key={p.key + "-sub"} className="px-4 py-1.5 border-l border-[var(--color-edify-divider)]">
                    <div className="grid grid-cols-3 gap-3 t-tiny font-semibold text-muted uppercase tracking-[0.08em] text-right tabular">
                      <span title="Target">Tgt</span>
                      <span title="Achieved">Ach</span>
                      <span>%</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const RIcon = METRIC_ICON[r.iconKey];
                return (
                <tr key={r.key} className="border-t border-[var(--color-edify-divider)]">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className={cn("h-7 w-7 rounded-md grid place-items-center shrink-0", r.iconBg, r.iconText)}>
                        <RIcon size={13} />
                      </span>
                      <div className="t-body font-bold truncate">{r.label}</div>
                    </div>
                  </td>
                  {PERIODS.map((p) => {
                    const c = r.cells[p.key];
                    return (
                      <td key={p.key} className="px-4 py-2 border-l border-[var(--color-edify-divider)]">
                        <div className="grid grid-cols-3 gap-3 t-caption tabular text-right items-center">
                          <span className="text-muted">{c.target}</span>
                          <span className="font-semibold">{c.achieved}</span>
                          <span className={cn("font-semibold justify-self-end", STATUS_TEXT[c.status])}>{c.pct}%</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
                );
              })}
              <tr className="border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40">
                <td className="px-4 py-2.5 t-caption font-extrabold">Overall Progress</td>
                {PERIODS.map((p) => {
                  const c = periodAgg[p.key];
                  return (
                    <td key={p.key} className="px-3 py-2 border-l border-[var(--color-edify-divider)] text-center">
                      <span className={cn("t-body-lg font-extrabold", STATUS_TEXT[c.status])}>{c.pct}%</span>
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Bottom row — 4 cards */}
      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <ProgressTrendCard data={data.trend} />
        <ContributionCard rows={rows} periodAgg={periodAgg} />
        <PerformanceDistributionCard distribution={distribution} />
        <TopFocusCard items={data.topFocus} />
      </section>
    </div>
  );
}

// ────────── Sub-cards ──────────

function ProgressTrendCard({ data }: { data: OperatingTargets["trend"] }) {
  return (
    <div className="card p-3.5">
      <header className="flex items-center justify-between mb-3">
        <h3 className="t-body-lg font-extrabold tracking-tight">Progress Trend (Cumulative)</h3>
      </header>
      <div className="flex items-center gap-4 t-caption mb-2">
        <span className="inline-flex items-center gap-1.5 font-semibold">
          <span className="h-2 w-2 rounded-full bg-blue-500" /> Actual
        </span>
        <span className="inline-flex items-center gap-1.5 font-semibold text-muted">
          <span className="h-2 w-2 rounded-full bg-slate-300" /> Target
        </span>
      </div>
      <div className="h-[200px]">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="var(--color-edify-divider)" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8a96a1" }} tickLine={false} axisLine={{ stroke: "#eef2f4" }} />
            <YAxis tick={{ fontSize: 10, fill: "#8a96a1" }} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} domain={[0, 100]} />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #eef2f4" }}
              formatter={(value, name) => [`${String(value)}%`, String(name)]}
            />
            <Line type="monotone" dataKey="actual" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 4 }} />
            <Line type="monotone" dataKey="target" stroke="#cbd5dd" strokeWidth={1.5} strokeDasharray="3 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-center justify-between t-tiny muted mt-2 px-1">
        <span>Q1</span><span>Q2</span><span className="font-bold">MID YEAR</span><span>Q3</span><span>Q4</span>
      </div>
    </div>
  );
}

function ContributionCard({ rows, periodAgg }: { rows: ComputedRow[]; periodAgg: Record<PeriodKey, { pct: number }> }) {
  void rows;
  const items: { label: string; pct: number; color: string }[] = [
    { label: "Monthly (Nov)",            pct: periodAgg.monthly.pct, color: "bg-blue-500"    },
    { label: `+ ${quarterLabel("Q1")}`,  pct: periodAgg.q1.pct,      color: "bg-emerald-500" },
    { label: `+ ${quarterLabel("Q2")}`,  pct: periodAgg.q2.pct,      color: "bg-blue-400"    },
    { label: `= Mid Year (${MID_YEAR_MONTH_RANGE})`, pct: periodAgg.midYear.pct, color: "bg-violet-500" },
    { label: `+ ${quarterLabel("Q3")}`,  pct: periodAgg.q3.pct,      color: "bg-amber-500"   },
    { label: `+ ${quarterLabel("Q4")}`,  pct: periodAgg.q4.pct,      color: "bg-rose-500"    },
    { label: "= Full Year",              pct: periodAgg.fy.pct,      color: "bg-indigo-500"  },
  ];
  return (
    <div className="card p-3.5">
      <header className="mb-3">
        <h3 className="t-body-lg font-extrabold tracking-tight">Contribution to Roll-up</h3>
      </header>
      <ul className="space-y-2">
        {items.map((it) => (
          <li key={it.label} className="flex items-center gap-2 t-caption">
            <span className="w-[125px] shrink-0 text-secondary">{it.label}</span>
            <div className="flex-1 h-2 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
              <div className={cn("h-full rounded-full", it.color)} style={{ width: `${Math.min(it.pct, 100)}%` }} />
            </div>
            <span className="w-9 text-right font-extrabold tabular">{it.pct}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PerformanceDistributionCard({
  distribution,
}: {
  distribution: { onTrack: number; atRisk: number; offTrack: number; total: number };
}) {
  const { onTrack, atRisk, offTrack, total } = distribution;
  const size = 130;
  const stroke = 16;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const segs = total === 0
    ? []
    : [
        { len: (onTrack / total) * c,  color: "#10b981" },
        { len: (atRisk / total) * c,   color: "#f59e0b" },
        { len: (offTrack / total) * c, color: "#ef4444" },
      ];
  let acc = 0;
  return (
    <div className="card p-3.5">
      <header className="mb-3">
        <h3 className="t-body-lg font-extrabold tracking-tight">Performance Distribution</h3>
      </header>
      <div className="flex items-center gap-3">
        <div className="relative shrink-0" style={{ width: size, height: size }}>
          <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-edify-divider)" strokeWidth={stroke} />
            {segs.map((s, i) => {
              const dash = s.len;
              const offset = -acc;
              acc += dash;
              return (
                <circle
                  key={i}
                  cx={size / 2}
                  cy={size / 2}
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={stroke}
                  strokeDasharray={`${dash} ${c - dash}`}
                  strokeDashoffset={offset}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`}
                />
              );
            })}
          </svg>
          <div className="absolute inset-0 grid place-items-center text-center">
            <div>
              <div className="t-h-sm leading-none">{total}</div>
              <div className="t-tiny muted mt-0.5">Total<br/>Areas</div>
            </div>
          </div>
        </div>
        <ul className="flex-1 space-y-1.5 t-caption">
          <DistRow color="bg-emerald-500" label="On Track (≥70%)" count={onTrack} total={total} />
          <DistRow color="bg-amber-500"  label="At Risk (50-69%)" count={atRisk}  total={total} />
          <DistRow color="bg-rose-500"   label="Off Track (<50%)" count={offTrack} total={total} />
        </ul>
      </div>
    </div>
  );
}

function DistRow({ color, label, count, total }: { color: string; label: string; count: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((count / total) * 100);
  return (
    <li className="flex items-center gap-2">
      <span className={cn("h-2 w-2 rounded-full shrink-0", color)} />
      <span className="text-secondary font-semibold flex-1">{label}</span>
      <span className="font-extrabold">{count}</span>
      <span className="muted">({pct}%)</span>
    </li>
  );
}

function TopFocusCard({ items }: { items: OperatingTargets["topFocus"] }) {
  return (
    <div className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between mb-3">
        <h3 className="t-body-lg font-extrabold tracking-tight">Top Areas to Focus</h3>
      </header>
      <ul className="space-y-2 flex-1">
        {items.map((it) => (
          <li key={it.rank} className="flex items-start gap-2.5">
            <span className="h-6 w-6 rounded-md bg-[var(--color-edify-soft)] text-secondary grid place-items-center t-caption font-extrabold shrink-0">{it.rank}</span>
            <div className="flex-1 min-w-0">
              <div className="t-body font-extrabold tracking-tight truncate">{it.label}</div>
              <div className="t-caption muted truncate">{it.detail}</div>
            </div>
            <HealthPill status={it.status} size="xs" />
          </li>
        ))}
      </ul>
      <Link
        href="/analytics"
        className="t-caption font-semibold text-[var(--color-edify-primary)] hover:underline mt-3 text-left inline-flex items-center gap-1"
      >
        View all insights →
      </Link>
    </div>
  );
}

// ────────── Page-level header ──────────
//
// Rendered ONCE per page at the top (above the welcome hero) so the
// chrome — title · period filters · Filters · Export Report · search
// · message · bell · avatar — lives in one canonical strip. The view
// body (`OperatingTargetsView`) no longer renders its own PageHeader,
// which removes the duplicate narrow-title-with-wide-chrome strip
// that previously appeared mid-page.

export function OperatingTargetsPageHeader({
  data,
  scope,
}: {
  data: OperatingTargets;
  /** Role-scoped filter options, computed server-side by the route and
   *  passed down (this component is client). When omitted, the header
   *  renders without the filter bar. */
  scope?: FilterScope;
}) {
  const exportRows = data.metrics.map((m) => {
    const c = computeRow(m, data.startedPeriods).cells;
    return {
      Metric: m.label,
      Monthly_target: c.monthly.target, Monthly_achieved: c.monthly.achieved,
      Q1_target: c.q1.target, Q1_achieved: c.q1.achieved,
      Q2_target: c.q2.target, Q2_achieved: c.q2.achieved,
      MidYear_target: c.midYear.target, MidYear_achieved: c.midYear.achieved,
      Q3_target: c.q3.target, Q3_achieved: c.q3.achieved,
      Q4_target: c.q4.target, Q4_achieved: c.q4.achieved,
      FY_target: c.fy.target, FY_achieved: c.fy.achieved, FY_pct: c.fy.pct,
    };
  });
  return (
    <PageHeader
      title={data.scope}
      subtitle="Track your performance across all time periods. Monthly progress rolls up to Quarterly, Mid Year, and FY targets."
      filterBar={scope ? <HeaderFilterBar scope={scope} /> : undefined}
      actions={
        <ExportButton
          rows={exportRows}
          filename={`${data.scope.replace(/\s+/g, "-").toLowerCase()}-targets-${data.fiscalYearLabel.replace(/\s+/g, "")}`}
          label="Export Report"
          className="!h-10 !px-3.5 !rounded-xl !bg-[var(--color-edify-primary)] !text-white !border-transparent hover:!opacity-95 t-body"
        />
      }
    />
  );
}

