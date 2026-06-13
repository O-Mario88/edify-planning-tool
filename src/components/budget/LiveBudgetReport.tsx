"use client";

// Live budget reporting — reads the SAME backend spine the dashboards use
// (/api/budget/from-schedule): every figure is the caller's scheduled activities
// auto-costed from the CD rate card. No mock. Two views share one fetch:
//   • "breakdown" — annual total split by activity type + staff/partner delivery
//   • "monthly"   — month-by-month + quarterly roll-up + busy/slow intelligence

import { useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, TrendingUp, TrendingDown } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";
import type { BeBudgetFromSchedule } from "@/lib/api/surfaces";

type Data = Omit<BeBudgetFromSchedule, "live">;

const ugx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${Math.round(n / 1_000)}K` : `UGX ${Math.round(n)}`;
const fullUgx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;

const TYPE_LABEL: Record<string, string> = {
  school_visit: "School visits", follow_up_visit: "Follow-up visits", coaching_visit: "Coaching visits",
  in_school_support: "In-school support", training: "Trainings", school_improvement_training: "SIT / SSA",
  cluster_meeting: "Cluster meetings", cluster_training: "Cluster trainings", ssa_activity: "SSA activities",
  project_activity: "Project activities", partner_activity: "Partner activities", core_visit: "Core visits", core_training: "Core trainings",
};
const SCOPE_LABEL: Record<string, string> = { own: "your schedule", team: "your team's schedule", country: "the country's schedule" };

export function LiveBudgetReport({ view }: { view: "breakdown" | "monthly" }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/budget/from-schedule", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setData(j as Data); else setError(j.error || "Could not load the budget"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  if (loading) return <div className="card p-4"><LoadingState /></div>;
  if (error) return <div className="card p-4"><ErrorState message={error} onRetry={load} /></div>;
  if (!data || data.activityCount === 0)
    return <div className="card p-4"><EmptyState title="No scheduled activities yet" message="The budget builds itself from scheduled, costed activities. Schedule visits or trainings to populate it." /></div>;

  const maxMonth = Math.max(1, ...data.byMonth.map((m) => m.amount));
  const busy = new Set(data.busyMonths.map((m) => m.month));
  const slow = new Set(data.slowMonths.map((m) => m.month));

  return (
    <div className="space-y-3">
      {/* Headline + provenance */}
      <section className="card p-4">
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <div>
            <div className="text-[28px] font-extrabold tabular leading-none">{fullUgx(data.total)}</div>
            <div className="text-[12px] muted mt-1">
              {data.activityCount} scheduled activities in {SCOPE_LABEL[data.scope]} · FY{data.fy} · auto-costed from the CD rate card
            </div>
          </div>
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2.5 py-1 text-[11px] font-bold border border-[var(--color-edify-border)]">Live · scoped · backend-driven</span>
        </div>
        {(data.costMissingCount > 0 || data.unscheduledCount > 0) && (
          <div className="flex flex-wrap gap-2 mt-3">
            {data.costMissingCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-2 py-1 text-[11px] font-bold">
                <AlertTriangle size={13} /> {data.costMissingCount} activities missing a cost rate — fund request blocked
              </span>
            )}
            {data.unscheduledCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 text-amber-700 px-2 py-1 text-[11px] font-bold">
                <CalendarClock size={13} /> {data.unscheduledCount} not yet on the calendar ({ugx(data.unscheduledAmount)})
              </span>
            )}
          </div>
        )}
      </section>

      {view === "breakdown" ? (
        <>
          {/* By activity type — every line traces to a costed activity type */}
          <section className="card p-4">
            <h2 className="text-[13px] font-extrabold tracking-tight mb-3">Budget by activity type</h2>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left muted uppercase text-[10px] tracking-wide border-b border-[var(--color-edify-border)]">
                  <th className="py-1.5">Activity type</th><th className="py-1.5 text-right">Activities</th>
                  <th className="py-1.5 text-right">Amount</th><th className="py-1.5 text-right">% of total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-edify-divider)]">
                {data.byType.map((t) => (
                  <tr key={t.type}>
                    <td className="py-1.5 font-semibold">{TYPE_LABEL[t.type] ?? t.type}</td>
                    <td className="py-1.5 text-right tabular muted">{t.count}</td>
                    <td className="py-1.5 text-right tabular font-bold">{fullUgx(t.amount)}</td>
                    <td className="py-1.5 text-right tabular muted">{data.total ? Math.round((t.amount / data.total) * 100) : 0}%</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-[var(--color-edify-border)] font-extrabold">
                  <td className="py-1.5">Total</td><td className="py-1.5 text-right tabular">{data.activityCount}</td>
                  <td className="py-1.5 text-right tabular">{fullUgx(data.total)}</td><td className="py-1.5 text-right">100%</td>
                </tr>
              </tfoot>
            </table>
          </section>

          {/* Staff vs partner delivery split */}
          <section className="card p-4">
            <h2 className="text-[13px] font-extrabold tracking-tight mb-3">Delivery split</h2>
            <div className="grid grid-cols-2 gap-3">
              <Split label="Staff-delivered" amount={data.byDelivery.staff.amount} count={data.byDelivery.staff.count} total={data.total} color="bg-sky-500" />
              <Split label="Partner-delivered" amount={data.byDelivery.partner.amount} count={data.byDelivery.partner.count} total={data.total} color="bg-violet-500" />
            </div>
          </section>
        </>
      ) : (
        <>
          {/* Month-by-month */}
          <section className="card p-4">
            <h2 className="text-[13px] font-extrabold tracking-tight mb-3">Monthly funding need</h2>
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left muted uppercase text-[10px] tracking-wide border-b border-[var(--color-edify-border)]">
                  <th className="py-1.5">Month</th><th className="py-1.5 text-right">Activities</th>
                  <th className="py-1.5 text-right">Trainings</th><th className="py-1.5 text-right">Amount</th><th className="py-1.5 w-[30%]"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-edify-divider)]">
                {data.byMonth.filter((m) => m.count > 0).map((m) => (
                  <tr key={m.month} className={cn(busy.has(m.month) && "bg-rose-50/40", slow.has(m.month) && "bg-amber-50/40")}>
                    <td className="py-1.5 font-semibold">{m.label}{busy.has(m.month) && <span className="ml-1 text-[9px] text-rose-600 font-bold">BUSY</span>}{slow.has(m.month) && <span className="ml-1 text-[9px] text-amber-600 font-bold">SLOW</span>}</td>
                    <td className="py-1.5 text-right tabular muted">{m.count}</td>
                    <td className="py-1.5 text-right tabular muted">{m.trainings}</td>
                    <td className="py-1.5 text-right tabular font-bold">{fullUgx(m.amount)}</td>
                    <td className="py-1.5 pl-2"><div className="h-2 rounded-full bg-slate-100 overflow-hidden"><div className={cn("h-full rounded-full", busy.has(m.month) ? "bg-rose-400" : slow.has(m.month) ? "bg-amber-400" : "bg-[var(--color-edify-primary)]")} style={{ width: `${(m.amount / maxMonth) * 100}%` }} /></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Quarterly roll-up */}
          <section className="card p-4">
            <h2 className="text-[13px] font-extrabold tracking-tight mb-3">Quarterly roll-up</h2>
            <MetricStrip
              bare
              columns="grid-cols-2 sm:grid-cols-4"
              metrics={data.byQuarter.map((q) => ({
                key: q.quarter,
                label: q.quarter,
                value: ugx(q.amount),
                caption: `${q.count} activities`,
              }))}
            />
          </section>

          {/* Busy/slow intelligence */}
          {(data.busyMonths.length > 0 || data.slowMonths.length > 0) && (
            <section className="card p-4 space-y-1.5">
              <h2 className="text-[13px] font-extrabold tracking-tight mb-1">Capacity intelligence</h2>
              {data.busyMonths.map((m) => (
                <div key={`b${m.month}`} className="text-[12px] text-rose-700 inline-flex items-center gap-1.5"><TrendingUp size={13} /> {m.insight}</div>
              ))}
              {data.slowMonths.map((m) => (
                <div key={`s${m.month}`} className="text-[12px] text-amber-700 inline-flex items-center gap-1.5 block"><TrendingDown size={13} /> {m.insight}</div>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Split({ label, amount, count, total, color }: { label: string; amount: number; count: number; total: number; color: string }) {
  const pct = total ? Math.round((amount / total) * 100) : 0;
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-3">
      <div className="text-[11px] muted font-semibold">{label}</div>
      <div className="text-[18px] font-extrabold tabular mt-1">{fullUgx(amount)}</div>
      <div className="text-[10px] muted mt-0.5">{count} activities · {pct}%</div>
      <div className="h-1.5 rounded-full bg-slate-100 mt-2 overflow-hidden"><div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} /></div>
    </div>
  );
}
