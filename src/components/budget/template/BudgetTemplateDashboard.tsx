"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell,
  LineChart, Line, CartesianGrid, Legend,
} from "recharts";
import {
  CalendarDays, ChevronRight, ClipboardCheck, Lightbulb, Wallet,
} from "lucide-react";
import type { BeBudgetBoard } from "@/lib/api/surfaces";
import type { EdifyRole } from "@/lib/auth-public";
import { fmtUgx } from "@/lib/funds/budget/budget-format";
import { BudgetWorkflowPanel } from "@/components/budget/template/BudgetWorkflowPanel";
import { cn } from "@/lib/utils";

/** Edify FY month order (Oct → Sep). */
const FY_MONTHS = [
  { n: 10, label: "Oct" }, { n: 11, label: "Nov" }, { n: 12, label: "Dec" },
  { n: 1, label: "Jan" }, { n: 2, label: "Feb" }, { n: 3, label: "Mar" },
  { n: 4, label: "Apr" }, { n: 5, label: "May" }, { n: 6, label: "Jun" },
  { n: 7, label: "Jul" }, { n: 8, label: "Aug" }, { n: 9, label: "Sep" },
];

const QMONTHS: Record<string, number[]> = {
  Q1: [10, 11, 12], Q2: [1, 2, 3], Q3: [4, 5, 6], Q4: [7, 8, 9],
};

const PERIOD_TABS = [
  { key: "overview", label: "Overview", lens: null as string | null },
  { key: "week", label: "Weekly", lens: "week" },
  { key: "month", label: "Monthly", lens: "month" },
  { key: "quarter", label: "Quarterly", lens: "quarter" },
  { key: "year", label: "Yearly", lens: "year" },
] as const;

/** Steel-blue chart palette — matches globals.css Edify tokens (#50758b family). */
const CHART = ["#50758b", "#638aa1", "#7a9db0", "#89a7b8", "#a3bac8", "#2f4a59", "#28404d"];
const DONUT = ["#50758b", "#638aa1", "#7a9db0", "#a3bac8", "#c5d4de", "#2f4a59"];
const GRID_STROKE = "#eaeff2";
const TICK_FILL = "#50758b";

type Props = {
  initial: Omit<BeBudgetBoard, "live">;
  role: EdifyRole;
  subtitle?: string;
  compact?: boolean;
};

type TabKey = typeof PERIOD_TABS[number]["key"] | `m-${number}`;

function fmtIndex(n: number) {
  return String(n).padStart(2, "0");
}

function fmtShort(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(Math.round(n));
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-[var(--color-edify-dark)] text-white text-[11px] font-extrabold uppercase tracking-wider px-3 py-2">
      {children}
    </div>
  );
}

function GlanceRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--color-edify-divider)] last:border-0 text-[12px]">
      <span className="text-[var(--color-edify-muted)] font-medium">{label}</span>
      <span className={cn("font-extrabold tabular", highlight ? "text-[var(--color-edify-primary)]" : "text-[var(--color-edify-text)]")}>{value}</span>
    </div>
  );
}

export function BudgetTemplateDashboard({ initial, role, subtitle, compact }: Props) {
  const [data, setData] = useState(initial);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (opts: { lens?: string; month?: number }) => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ fy: initial.fy });
      if (opts.lens) q.set("lens", opts.lens);
      if (opts.month) q.set("month", String(opts.month));
      const res = await fetch(`/api/budget/board?${q}`, { credentials: "include" });
      const j = await res.json();
      if (j.live) setData(j);
    } finally {
      setLoading(false);
    }
  }, [initial.fy]);

  useEffect(() => {
    if (activeTab === "overview") {
      if (data.lens !== "year") void load({ lens: "year" });
      return;
    }
    const period = PERIOD_TABS.find((t) => t.key === activeTab);
    if (period?.lens) {
      void load({ lens: period.lens });
      return;
    }
    if (activeTab.startsWith("m-")) {
      const month = Number(activeTab.slice(2));
      void load({ lens: "month", month });
    }
  }, [activeTab, load]);

  const s = data.summary;
  const isRvp = role === "RVP" || data.viewMode === "country_summary";
  const isPl = role === "CountryProgramLead" || data.viewMode === "team";
  const isOwn = data.viewMode === "own";

  const monthMap = useMemo(
    () => new Map(data.byMonth.map((m) => [m.month, m])),
    [data.byMonth],
  );

  const fyMonthRows = useMemo(
    () =>
      FY_MONTHS.map(({ n, label }) => {
        const row = monthMap.get(n) ?? { month: n, label, amount: 0, count: 0 };
        return { ...row, shortLabel: label };
      }),
    [monthMap],
  );

  const fyTotal = s.fiscalYear || fyMonthRows.reduce((sum, r) => sum + r.amount, 0);
  const monthsWithWork = fyMonthRows.filter((r) => r.count > 0);
  const avgMonthly = monthsWithWork.length ? fyTotal / monthsWithWork.length : 0;

  const barChartData = fyMonthRows.map((r) => ({
    label: r.shortLabel,
    planned: r.amount,
    activities: r.count,
    variance: r.amount - avgMonthly,
  }));

  const lineChartData = fyMonthRows.map((r) => ({
    label: r.shortLabel,
    sharePct: fyTotal > 0 ? Math.round((r.amount / fyTotal) * 1000) / 10 : 0,
    amount: r.amount,
  }));

  const quarterRows = useMemo(
    () =>
      Object.entries(QMONTHS).map(([q, months]) => {
        const rows = fyMonthRows.filter((r) => months.includes(r.month));
        const planned = rows.reduce((sum, r) => sum + r.amount, 0);
        const count = rows.reduce((sum, r) => sum + r.count, 0);
        const sharePct = fyTotal > 0 ? Math.round((planned / fyTotal) * 1000) / 10 : 0;
        const targetPct = q === "Q1" ? 25 : q === "Q2" ? 50 : q === "Q3" ? 75 : 100;
        const variance = sharePct - targetPct;
        return { quarter: q, planned, count, sharePct, targetPct, variance };
      }),
    [fyMonthRows, fyTotal],
  );

  const categoryDonut = data.byCategory.slice(0, 6);
  const topCategories = data.byCategory.slice(0, 8);

  const title = isRvp ? "Annual Budget Overview" : isOwn ? "My Plan Budget" : "Annual Budget Overview";

  return (
    <div className={cn("rounded-xl overflow-hidden border border-[var(--color-edify-border)] bg-[var(--color-page)] shadow-sm", compact ? "" : "mt-1")}>
      {/* ── Header band (spreadsheet title row) ── */}
      <div className="bg-white border-b border-[var(--color-edify-divider)] px-4 md:px-6 py-4 flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <h2 className="text-[18px] md:text-[22px] font-extrabold tracking-tight text-[var(--color-edify-text)] uppercase">
            {title}
          </h2>
          <p className="text-[12px] text-[var(--color-edify-muted)] mt-0.5 max-w-lg">
            {subtitle ??
              (isRvp
                ? "Consolidated country budget — CD-approved plans at a glance."
                : isPl
                  ? "Team and personal plan budget — costed from scheduled activities."
                  : "See your whole fiscal year at a glance — every cost from the plan and cost catalogue.")}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="border border-[var(--color-edify-border)] rounded-lg overflow-hidden flex text-[11px]">
            <div className="bg-[var(--color-edify-soft)] px-2.5 py-1.5 font-bold text-[var(--color-edify-dark)] uppercase tracking-wide">FY</div>
            <div className="bg-white px-3 py-1.5 font-extrabold tabular text-[var(--color-edify-text)]">{data.fy}</div>
          </div>
          <div className="border border-[var(--color-edify-border)] rounded-lg overflow-hidden flex text-[11px]">
            <div className="bg-[var(--color-edify-soft)] px-2.5 py-1.5 font-bold text-[var(--color-edify-dark)] uppercase tracking-wide">Currency</div>
            <div className="bg-white px-3 py-1.5 font-extrabold text-[var(--color-edify-text)]">UGX</div>
          </div>
          {loading && (
            <span className="text-[11px] font-semibold text-[var(--color-edify-primary)] flex items-center gap-1">
              <CalendarDays size={12} /> Updating…
            </span>
          )}
        </div>
      </div>

      <div className="p-3 md:p-4 space-y-3">
        {/* ── Row 1: Glance + bar chart + donut ── */}
        <div className="grid grid-cols-12 gap-3">
          {/* Year at a Glance */}
          <div className="col-span-12 lg:col-span-3 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Year at a Glance</SectionHeader>
            <GlanceRow label="Fiscal year planned" value={fmtUgx(fyTotal)} />
            <GlanceRow label="This month" value={fmtUgx(s.thisMonth)} />
            <GlanceRow label="This week" value={fmtUgx(s.thisWeek)} />
            <GlanceRow label="Next week" value={fmtUgx(s.nextWeek)} />
            <GlanceRow label="This quarter" value={fmtUgx(s.thisQuarter)} />
            <GlanceRow label="Activities scheduled" value={String(s.activityCount)} />
            <GlanceRow
              label="Cost catalogue gaps"
              value={String(s.costMissingCount)}
              highlight={s.costMissingCount === 0}
            />
            <GlanceRow label="Period view" value={data.lensLabel} />
          </div>

          {/* Grouped bar — planned / activities / variance */}
          <div className="col-span-12 lg:col-span-6 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Planned · Activities · vs Monthly Avg</SectionHeader>
            <div className="p-3 h-[240px]">
              {barChartData.some((d) => d.planned > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: TICK_FILL }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={fmtShort} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(v, name) =>
                        name === "activities" ? [v, "Activities"] : [fmtUgx(Number(v)), String(name)]
                      }
                    />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Bar yAxisId="left" dataKey="planned" name="Planned" fill="#50758b" radius={[2, 2, 0, 0]} />
                    <Bar yAxisId="right" dataKey="activities" name="Activities" fill="#638aa1" radius={[2, 2, 0, 0]} />
                    <Bar yAxisId="left" dataKey="variance" name="vs Avg" fill="#a3bac8" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-[12px] muted text-center py-16">Schedule activities to populate the monthly chart.</p>
              )}
            </div>
          </div>

          {/* Category donut */}
          <div className="col-span-12 lg:col-span-3 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Category Breakdown</SectionHeader>
            <div className="p-2 h-[240px]">
              {categoryDonut.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={categoryDonut} dataKey="amount" nameKey="label" cx="50%" cy="45%" innerRadius={42} outerRadius={68} paddingAngle={2}>
                      {categoryDonut.map((_, i) => (
                        <Cell key={i} fill={DONUT[i % DONUT.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => fmtUgx(Number(v))} />
                    <Legend wrapperStyle={{ fontSize: 9 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-[12px] muted text-center py-16">No categories yet.</p>
              )}
            </div>
          </div>
        </div>

        {/* ── Row 2: Monthly summary table + category detail donut ── */}
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 lg:col-span-7 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Monthly Summary</SectionHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-[var(--color-edify-soft)]/60 text-[10px] uppercase tracking-wide text-[var(--color-edify-dark)]">
                    <th className="text-left font-bold px-3 py-2">Month</th>
                    <th className="text-right font-bold px-3 py-2">Planned</th>
                    <th className="text-right font-bold px-3 py-2">Activities</th>
                    <th className="text-right font-bold px-3 py-2">FY Share</th>
                    <th className="text-right font-bold px-3 py-2">vs Avg</th>
                  </tr>
                </thead>
                <tbody>
                  {fyMonthRows.map((r) => {
                    const share = fyTotal > 0 ? (r.amount / fyTotal) * 100 : 0;
                    const diff = r.amount - avgMonthly;
                    return (
                      <tr key={r.month} className="border-t border-[var(--color-edify-divider)] hover:bg-[var(--color-edify-soft)]/40">
                        <td className="px-3 py-1.5 font-semibold text-[var(--color-edify-text)]">{r.shortLabel}</td>
                        <td className="px-3 py-1.5 text-right tabular">{r.amount ? fmtUgx(r.amount) : "—"}</td>
                        <td className="px-3 py-1.5 text-right tabular">{r.count || "—"}</td>
                        <td className="px-3 py-1.5 text-right tabular">{share ? `${share.toFixed(1)}%` : "—"}</td>
                        <td className={cn("px-3 py-1.5 text-right tabular font-semibold", diff >= 0 ? "text-[var(--color-edify-primary)]" : "text-rose-600")}>
                          {r.amount ? fmtUgx(diff) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="border-t-2 border-[var(--color-edify-dark)] bg-[var(--color-edify-soft)]/40 font-extrabold">
                    <td className="px-3 py-2 text-[var(--color-edify-text)]">TOTAL</td>
                    <td className="px-3 py-2 text-right tabular">{fmtUgx(fyTotal)}</td>
                    <td className="px-3 py-2 text-right tabular">{fyMonthRows.reduce((n, r) => n + r.count, 0)}</td>
                    <td className="px-3 py-2 text-right tabular">100%</td>
                    <td className="px-3 py-2 text-right tabular">—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="col-span-12 lg:col-span-5 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Activity Category Split</SectionHeader>
            <div className="p-3 flex flex-col md:flex-row gap-3 min-h-[220px]">
              {topCategories.length > 0 ? (
                <>
                  <div className="flex-1 h-[180px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={topCategories} dataKey="amount" nameKey="label" cx="50%" cy="50%" outerRadius={72} paddingAngle={1}>
                          {topCategories.map((_, i) => (
                            <Cell key={i} fill={CHART[i % CHART.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v) => fmtUgx(Number(v))} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className="md:w-[42%] space-y-1.5 text-[11px]">
                    {topCategories.map((c, i) => (
                      <li key={c.label} className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: CHART[i % CHART.length] }} />
                        <span className="flex-1 font-medium truncate">{c.label}</span>
                        <span className="tabular font-bold">{fmtUgx(c.amount)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="text-[12px] muted m-auto">No category data for this period.</p>
              )}
            </div>
          </div>
        </div>

        {/* ── Row 3: Quarter projections + line trend ── */}
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 lg:col-span-5 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>Quarterly Projections</SectionHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-[var(--color-edify-soft)]/60 text-[10px] uppercase tracking-wide text-[var(--color-edify-dark)]">
                    <th className="text-left font-bold px-3 py-2">Quarter</th>
                    <th className="text-right font-bold px-3 py-2">Planned</th>
                    <th className="text-right font-bold px-3 py-2">Activities</th>
                    <th className="text-right font-bold px-3 py-2">FY Share</th>
                    <th className="text-right font-bold px-3 py-2">Variance</th>
                  </tr>
                </thead>
                <tbody>
                  {quarterRows.map((r) => (
                    <tr key={r.quarter} className="border-t border-[var(--color-edify-divider)]">
                      <td className="px-3 py-1.5 font-semibold">{r.quarter}</td>
                      <td className="px-3 py-1.5 text-right tabular">{r.planned ? fmtUgx(r.planned) : "—"}</td>
                      <td className="px-3 py-1.5 text-right tabular">{r.count || "—"}</td>
                      <td className="px-3 py-1.5 text-right tabular">{r.sharePct ? `${r.sharePct}%` : "—"}</td>
                      <td className={cn("px-3 py-1.5 text-right tabular font-semibold", r.variance >= 0 ? "text-[var(--color-edify-primary)]" : "text-rose-600")}>
                        {r.planned ? `${r.variance >= 0 ? "+" : ""}${r.variance.toFixed(1)} pp` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="col-span-12 lg:col-span-7 bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
            <SectionHeader>FY Share Trend (% of annual planned)</SectionHeader>
            <div className="p-3 h-[200px]">
              {lineChartData.some((d) => d.amount > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={lineChartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: TICK_FILL }} />
                    <YAxis tick={{ fontSize: 10 }} unit="%" />
                    <Tooltip formatter={(v, name) => (name === "sharePct" ? [`${v}%`, "FY share"] : [fmtUgx(Number(v)), "Planned"])} />
                    <Line type="monotone" dataKey="sharePct" stroke="#2f4a59" strokeWidth={2} dot={{ r: 3, fill: "#50758b" }} name="sharePct" />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-[12px] muted text-center py-12">Trend line appears once months carry planned work.</p>
              )}
            </div>
          </div>
        </div>

        {/* ── Row 4: Approval workflow (live fund requests + country stages) ── */}
        {!compact && (
          <BudgetWorkflowPanel
            role={role}
            activityCount={s.activityCount}
            costMissingCount={s.costMissingCount}
          />
        )}

        {/* ── Activity budget table (grouped by category) ── */}
        <div className="bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
          <SectionHeader>
            {isRvp ? "Consolidated Activity Budget" : `Activity Budget · ${data.lensLabel}`}
          </SectionHeader>
          <div className="px-3 py-2 bg-[var(--color-edify-soft)]/30 border-b border-[var(--color-edify-divider)] flex items-center justify-between text-[11px]">
            <span className="font-semibold text-[var(--color-edify-primary)]">{data.lensLabel}</span>
            <span className="font-bold tabular text-[var(--color-edify-text)]">
              {fmtUgx(s.periodTotal)} · {s.activityCount} activities
            </span>
          </div>

          {data.grouped.length === 0 ? (
            <div className="p-8 text-center text-[12px] muted">
              No activities in this period. Schedule work in Planning — costs flow from the Country Cost Register.
            </div>
          ) : (
            data.grouped.map((cat) => (
              <div key={cat.category} className="border-b border-[var(--color-edify-divider)] last:border-0">
                <div className="px-3 py-1.5 bg-[var(--color-edify-soft)]/50 text-[10px] font-extrabold uppercase tracking-wide text-[var(--color-edify-dark)]">
                  {cat.category}
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="bg-[var(--color-page)] text-[10px] uppercase tracking-wide text-[var(--color-edify-primary)]">
                        <th className="text-left font-bold px-3 py-1.5 w-10">#</th>
                        <th className="text-left font-bold px-3 py-1.5">Activity</th>
                        <th className="text-right font-bold px-3 py-1.5">Number of School</th>
                        <th className="text-left font-bold px-3 py-1.5">Person Responsible</th>
                        <th className="text-right font-bold px-3 py-1.5">Unit Cost</th>
                        <th className="text-right font-bold px-3 py-1.5">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cat.rows.map((row) => (
                        <tr key={`${row.index}-${row.activity}-${row.responsible}`} className="border-t border-[var(--color-edify-divider)]/70 hover:bg-[var(--color-edify-soft)]/40">
                          <td className="px-3 py-2 font-bold tabular text-[var(--color-edify-primary)]">{fmtIndex(row.index)}</td>
                          <td className="px-3 py-2 font-semibold text-[var(--color-edify-text)]">{row.activity}</td>
                          <td className="px-3 py-2 text-right tabular">{row.schoolCount}</td>
                          <td className="px-3 py-2">{row.responsible}</td>
                          <td className={cn("px-3 py-2 text-right tabular", row.costMissing && "text-amber-700")}>
                            {row.unitCost != null ? fmtUgx(row.unitCost) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right font-extrabold tabular text-[var(--color-edify-dark)]">{fmtUgx(row.total)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </div>

        {/* ── Pro tip banner ── */}
        <div className="flex items-start gap-2 rounded-lg bg-[var(--color-edify-soft)]/80 border border-[var(--color-edify-border)] px-4 py-3 text-[11px] text-[var(--color-edify-dark)]">
          <Lightbulb size={16} className="shrink-0 mt-0.5 text-[var(--color-edify-primary)]" />
          <p>
            <strong>Workflow:</strong> Plans cost from the Country Cost Register → CCEO requests go to PL →
            PL/IA/Accountant roll up to CD (country submission) → CD adds admin cost → RVP final sign-off → Accountant disburses.
            Stages marked <strong>Soon</strong> are not yet wired to the live API.
            {s.costMissingCount > 0 && (
              <> Resolve <strong>{s.costMissingCount} cost gap{s.costMissingCount === 1 ? "" : "s"}</strong> before submitting.</>
            )}
          </p>
        </div>

        {/* Quick actions — role-accurate (CD does not approve field fund requests) */}
        <div className="flex flex-wrap gap-2">
          {role === "CCEO" && (
            <Link href="/weekly-funds" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <Wallet size={13} /> Submit fund request
            </Link>
          )}
          {role === "CountryProgramLead" && (
            <Link href="/approvals" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <ClipboardCheck size={13} /> Review CCEO requests
            </Link>
          )}
          {role === "CountryDirector" && (
            <Link href="/budget/intelligence" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <ClipboardCheck size={13} /> Country budget intelligence
            </Link>
          )}
          {role === "RVP" && (
            <Link href="/budget/approvals/rvp-queue" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <ClipboardCheck size={13} /> RVP final queue
            </Link>
          )}
          {role === "ProgramAccountant" && (
            <Link href="/approvals" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <Wallet size={13} /> Disburse approved
            </Link>
          )}
          {(role === "ImpactAssessment" || role === "Admin") && (
            <Link href="/planning" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors">
              <ClipboardCheck size={13} /> Open planning
            </Link>
          )}
          <Link
            href="/cost-catalogue"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-bold text-[var(--color-edify-dark)] hover:bg-[var(--color-edify-soft)]/40"
          >
            Cost Register
            <ChevronRight size={13} />
          </Link>
        </div>
      </div>

      {/* ── Bottom sheet tabs (Excel-style) ── */}
      <div className="border-t border-[var(--color-edify-border)] bg-[#e9ecef] px-1 py-0.5 flex overflow-x-auto gap-0.5">
        {PERIOD_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={cn(
              "shrink-0 px-3 py-1.5 text-[11px] font-bold rounded-t border border-b-0 transition-colors",
              activeTab === t.key
                ? "bg-white text-[var(--color-edify-dark)] border-[var(--color-edify-border)] shadow-sm"
                : "bg-[#dee2e6] text-[#495057] border-transparent hover:bg-[#ced4da]",
            )}
          >
            {t.label}
          </button>
        ))}
        {FY_MONTHS.map(({ n, label }) => {
          const key = `m-${n}` as TabKey;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={cn(
                "shrink-0 px-2.5 py-1.5 text-[11px] font-bold rounded-t border border-b-0 transition-colors",
                activeTab === key
                  ? "bg-white text-[var(--color-edify-dark)] border-[var(--color-edify-border)] shadow-sm"
                  : "bg-[#dee2e6] text-[#495057] border-transparent hover:bg-[#ced4da]",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
