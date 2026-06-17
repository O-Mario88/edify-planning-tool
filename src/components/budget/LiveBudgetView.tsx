import type { BeBudgetFromSchedule } from "@/lib/api/surfaces";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";

// Live annual budget — the financial expression of the plan, computed by the
// backend from SCHEDULED activities × the CD cost register (no mock figures).
// Empty until activities are scheduled; populates as the plan is built.

const fmtUgx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${(n / 1_000).toFixed(0)}K` : `UGX ${n.toLocaleString()}`;
const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function LiveBudgetView({ b }: { b: Omit<BeBudgetFromSchedule, "live"> }) {
  const metrics: MetricCell[] = [
    { key: "total", label: "Planned budget", value: fmtUgx(b.total), caption: `${b.activityCount} activities` },
    { key: "scheduled", label: "Scheduled", value: fmtUgx(b.scheduledTotal), caption: `${b.unscheduledCount} unscheduled` },
    { key: "staff", label: "Staff delivery", value: fmtUgx(b.byDelivery.staff.amount), caption: `${b.byDelivery.staff.count} activities` },
    { key: "partner", label: "Partner delivery", value: fmtUgx(b.byDelivery.partner.amount), caption: `${b.byDelivery.partner.count} activities` },
    { key: "avg", label: "Avg monthly", value: fmtUgx(b.avgMonthlyCost) },
    { key: "missing", label: "Cost-missing", value: b.costMissingCount, tone: b.costMissingCount ? "alert" : "good", caption: "no rate set" },
  ];

  if (b.activityCount === 0) {
    return (
      <>
        <MetricStrip metrics={metrics} />
        <div className="card p-6 text-center mt-4 text-[12px] muted">
          No activities scheduled yet for FY{b.fy} — the budget builds automatically as the plan is scheduled
          (each scheduled activity is costed from the CD Country Cost Register).
        </div>
      </>
    );
  }

  const maxQ = Math.max(1, ...b.byQuarter.map((q) => q.amount));
  return (
    <>
      <MetricStrip metrics={metrics} />
      <section className="grid grid-cols-12 gap-4 items-start mt-4">
        <div className="col-span-12 md:col-span-5 card p-4">
          <h3 className="text-[13px] font-extrabold tracking-tight mb-3">By quarter</h3>
          <div className="space-y-2">
            {b.byQuarter.map((q) => (
              <div key={q.quarter} className="flex items-center gap-2 text-[12px]">
                <span className="w-8 font-extrabold">{q.quarter}</span>
                <div className="flex-1 h-2 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
                  <div className="h-full bg-[var(--color-edify-primary)]" style={{ width: `${Math.round((q.amount / maxQ) * 100)}%` }} />
                </div>
                <span className="w-20 text-right tabular muted">{fmtUgx(q.amount)}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="col-span-12 md:col-span-7 card p-4">
          <h3 className="text-[13px] font-extrabold tracking-tight mb-3">By activity type</h3>
          <div className="divide-y divide-[var(--color-edify-divider)]">
            {b.byType.sort((a, z) => z.amount - a.amount).map((t) => (
              <div key={t.type} className="py-1.5 flex items-center justify-between text-[12px]">
                <span className="font-semibold">{titleCase(t.type)}</span>
                <span className={cn("tabular", t.amount ? "" : "muted")}>{fmtUgx(t.amount)} · {t.count}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
