import { Wallet, AlertTriangle } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetWeekly } from "@/lib/api/surfaces";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { MetricStrip } from "@/components/ui/MetricStrip";

// Live weekly fund needs — aggregated by the backend from SCHEDULED activities ×
// the CD cost register (/budget/weekly). Each line is a real costed activity, so
// the weekly total reconciles with the budget. Empty until activities are
// scheduled (an honest, real-pipeline empty state — never a fabricated total).

const fmtUgx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${(n / 1_000).toFixed(0)}K` : `UGX ${n.toLocaleString()}`;
const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export async function LiveWeeklyFunds() {
  const user = await getCurrentUser();
  const res = await fetchBudgetWeekly(user);
  if (!res.live) return <InsufficientData surface="weekly funds" />;
  const b = res.data;

  if (b.count === 0) {
    return (
      <section className="card p-6 text-center">
        <Wallet className="mx-auto mb-2 text-[var(--color-edify-muted)]" size={22} />
        <p className="text-[13px] font-extrabold tracking-tight">No weekly fund request yet</p>
        <p className="text-[12px] muted mt-1">
          Schedule activities from Planning to generate weekly fund needs. Each scheduled
          activity is costed from the CD Country Cost Register and rolled up into the week
          it falls in.
        </p>
      </section>
    );
  }

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Wallet size={14} /> Weekly fund needs · FY {b.fy}</h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>
      <MetricStrip
        bare
        className="mb-3"
        columns="grid-cols-2 sm:grid-cols-3"
        metrics={[
          { key: "total", label: "Total requested", value: fmtUgx(b.total) },
          { key: "count", label: "Activities", value: b.count },
          { key: "missing", label: "Cost-missing", value: b.costMissingCount, tone: b.costMissingCount ? "alert" : "default" },
        ]}
      />
      {b.costMissingCount > 0 && (
        <p className="text-[11px] text-amber-600 mb-2 inline-flex items-center gap-1">
          <AlertTriangle size={12} /> {b.costMissingCount} activities have no cost rate set — ask the CD to add a Country Cost Register rate.
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)]">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider font-bold muted border-b border-[var(--color-edify-divider)]">
              <th className="px-2.5 py-2">Week</th>
              <th className="px-2.5 py-2">Activity</th>
              <th className="px-2.5 py-2">Place</th>
              <th className="px-2.5 py-2">Delivery</th>
              <th className="px-2.5 py-2 text-right">Amount</th>
              <th className="px-2.5 py-2">Payment</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {b.lines.slice(0, 60).map((l) => (
              <tr key={l.id} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="px-2.5 py-2 tabular">{l.month ? `M${l.month}` : "—"}{l.week ? ` W${l.week}` : ""}</td>
                <td className="px-2.5 py-2 font-semibold">{titleCase(l.activityType)}</td>
                <td className="px-2.5 py-2 muted">{l.place}{l.district ? ` · ${l.district}` : ""}</td>
                <td className="px-2.5 py-2">{titleCase(l.deliveryType)}</td>
                <td className="px-2.5 py-2 text-right tabular font-extrabold">{l.costMissing ? "—" : fmtUgx(l.amount)}</td>
                <td className="px-2.5 py-2"><span className="text-[10px] muted">{titleCase(l.paymentStatus)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
