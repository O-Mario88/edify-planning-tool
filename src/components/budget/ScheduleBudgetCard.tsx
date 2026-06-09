"use client";

// Budget = the schedule, costed. The one card that proves the North Star spine:
// every scheduled activity is auto-costed from the CD rate card and rolled up to
// an annual budget, with busy/slow months and a staff/partner split falling
// straight out of the schedule. Backend-driven, role-scoped, no mock.

import { useEffect, useState } from "react";
import { Wallet, AlertTriangle, CalendarClock, TrendingUp, TrendingDown, Info } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeBudgetFromSchedule } from "@/lib/api/surfaces";

type Data = Omit<BeBudgetFromSchedule, "live">;

const ugx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${Math.round(n / 1_000)}K` : `UGX ${Math.round(n)}`;

const TYPE_LABEL: Record<string, string> = {
  school_visit: "School visits", follow_up_visit: "Follow-up visits", coaching_visit: "Coaching visits",
  in_school_support: "In-school support", training: "Trainings", school_improvement_training: "SIT / SSA",
  cluster_meeting: "Cluster meetings", cluster_training: "Cluster trainings", ssa_activity: "SSA activities",
  project_activity: "Project activities", partner_activity: "Partner activities", core_visit: "Core visits", core_training: "Core trainings",
};

const SCOPE_LABEL: Record<string, string> = { own: "your schedule", team: "your team's schedule", country: "the country schedule" };

export function ScheduleBudgetCard() {
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

  const maxMonth = data ? Math.max(1, ...data.byMonth.map((m) => m.amount)) : 1;
  const busy = new Set(data?.busyMonths.map((m) => m.month));
  const slow = new Set(data?.slowMonths.map((m) => m.month));

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Budget from your schedule{data ? ` · FY${data.fy}` : ""}</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped · auto-costed</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !data || data.activityCount === 0 ? (
        <EmptyState compact title="No scheduled activities yet" message="Schedule visits or trainings and the budget builds itself — each one is auto-costed from the CD rate card." />
      ) : (
        <>
          <p className="text-[11.5px] muted leading-snug mb-3 inline-flex items-start gap-1.5">
            <Info size={13} className="mt-px shrink-0 text-slate-400" />
            Every activity in {SCOPE_LABEL[data.scope]} is auto-costed from the CD rate card. You never calculate this by hand.
          </p>

          {/* Headline total */}
          <div className="flex items-end justify-between gap-3 mb-3">
            <div>
              <div className="text-[26px] font-extrabold tabular leading-none">{ugx(data.total)}</div>
              <div className="text-[11px] muted mt-1">{data.activityCount} scheduled activities · ~{ugx(data.avgMonthlyCost)}/active month</div>
            </div>
            <div className="text-right text-[11px]">
              <div className="inline-flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-sm bg-[var(--color-edify-primary)]" />
                <span className="muted">Staff</span><span className="font-bold tabular">{ugx(data.byDelivery.staff.amount)}</span>
              </div>
              <div className="inline-flex items-center gap-1.5 mt-0.5">
                <span className="inline-block w-2 h-2 rounded-sm bg-violet-500" />
                <span className="muted">Partner</span><span className="font-bold tabular">{ugx(data.byDelivery.partner.amount)}</span>
              </div>
            </div>
          </div>

          {/* Alerts: cost-missing + unscheduled */}
          {(data.costMissingCount > 0 || data.unscheduledCount > 0) && (
            <div className="flex flex-wrap gap-2 mb-3">
              {data.costMissingCount > 0 && (
                <span className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-2 py-1 text-[10.5px] font-bold">
                  <AlertTriangle size={12} /> {data.costMissingCount} missing a cost rate — fund request blocked
                </span>
              )}
              {data.unscheduledCount > 0 && (
                <span className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 text-amber-700 px-2 py-1 text-[10.5px] font-bold">
                  <CalendarClock size={12} /> {data.unscheduledCount} not on the calendar ({ugx(data.unscheduledAmount)})
                </span>
              )}
            </div>
          )}

          {/* Month distribution — busy (red) / slow (amber) fall out of the schedule */}
          <div className="mb-1.5 flex items-end gap-1 h-20">
            {data.byMonth.map((m) => {
              const h = Math.max(2, (m.amount / maxMonth) * 100);
              const tone = busy.has(m.month) ? "bg-rose-400" : slow.has(m.month) ? "bg-amber-400" : m.count ? "bg-[var(--color-edify-primary)]" : "bg-slate-200";
              return (
                <div key={m.month} className="flex-1 flex flex-col items-center justify-end gap-0.5 group relative">
                  {m.count > 0 && (
                    <div className="absolute -top-0.5 opacity-0 group-hover:opacity-100 transition text-[8.5px] font-bold whitespace-nowrap bg-slate-900 text-white px-1 py-0.5 rounded z-10 pointer-events-none">{ugx(m.amount)} · {m.count}</div>
                  )}
                  <div className={cn("w-full rounded-t", tone)} style={{ height: `${h}%` }} />
                  <div className="text-[8px] muted">{m.label[0]}</div>
                </div>
              );
            })}
          </div>

          {(data.busyMonths.length > 0 || data.slowMonths.length > 0) && (
            <div className="space-y-1 mb-2.5">
              {data.busyMonths.slice(0, 2).map((m) => (
                <div key={`b${m.month}`} className="text-[10.5px] text-rose-700 inline-flex items-center gap-1"><TrendingUp size={11} /> {m.insight}</div>
              ))}
              {data.slowMonths.slice(0, 2).map((m) => (
                <div key={`s${m.month}`} className="text-[10.5px] text-amber-700 inline-flex items-center gap-1 block"><TrendingDown size={11} /> {m.insight}</div>
              ))}
            </div>
          )}

          {/* Top activity types by cost */}
          <div className="border-t border-[var(--color-edify-divider)] pt-2 space-y-1">
            {data.byType.slice(0, 4).map((t) => (
              <div key={t.type} className="flex items-center justify-between text-[11px]">
                <span className="muted">{TYPE_LABEL[t.type] ?? t.type} <span className="text-slate-400">· {t.count}</span></span>
                <span className="font-bold tabular">{ugx(t.amount)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
