import { Wallet, AlertTriangle } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetFromSchedule, fetchFundRequests } from "@/lib/api/surfaces";
import { activeFinancialYear } from "@/lib/fy-engine";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { FundApprovalQueueLive } from "@/components/funds/FundApprovalQueueLive";
import { MetricStrip } from "@/components/ui/MetricStrip";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtUgx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${Math.round(n / 1_000)}K` : `UGX ${Math.round(n).toLocaleString()}`;

/** Live monthly fund request — costed from the schedule for the current month. */
export async function MonthlyFundRequestLive() {
  const user = await getCurrentUser();
  const fy = activeFinancialYear().id;
  const month = new Date().getMonth() + 1;
  const monthLabel = `${MONTHS[month]} ${fy}`;

  const [budgetRes, fundRes] = await Promise.all([
    fetchBudgetFromSchedule(user, fy),
    fetchFundRequests(user),
  ]);

  if (!budgetRes.live) return <InsufficientData surface="monthly fund request" />;

  const monthRow = budgetRes.data.byMonth.find((m) => m.month === month);
  const total = monthRow?.amount ?? 0;
  const count = monthRow?.count ?? 0;
  const costMissing = budgetRes.data.costMissingCount;
  const submitted = fundRes.live
    ? fundRes.data.find((r) => r.periodKey === `${fy}-M${month}`)
    : undefined;

  return (
    <div className="space-y-4">
      <section className="card p-3.5">
        <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Wallet size={14} /> Monthly fund request · {monthLabel}
          </h3>
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">
            Live · from schedule
          </span>
        </header>

        <MetricStrip
          bare
          className="mb-3"
          columns="grid-cols-2 sm:grid-cols-4"
          metrics={[
            { key: "total", label: "Month total", value: fmtUgx(total) },
            { key: "count", label: "Activities", value: count },
            { key: "missing", label: "Cost gaps", value: costMissing, tone: costMissing ? "alert" : "default" },
            { key: "status", label: "Request status", value: submitted?.status ?? "Not submitted" },
          ]}
        />

        {costMissing > 0 && (
          <p className="text-[11px] text-amber-600 mb-2 inline-flex items-center gap-1">
            <AlertTriangle size={12} /> {costMissing} activities are missing catalogue rates — fund submission is blocked until the CD adds them.
          </p>
        )}

        {count === 0 ? (
          <p className="text-[12px] muted">
            No costed activities scheduled for {monthLabel} yet. Schedule work from Planning and costs roll up here automatically.
          </p>
        ) : (
          <p className="text-[12px] muted">
            This total is auto-generated from scheduled activities at CD catalogue rates. Submit through the approval queue below when ready.
          </p>
        )}
      </section>

      <FundApprovalQueueLive
        canSubmit={user.role === "CCEO" || user.role === "CountryProgramLead"}
        canDisburse={user.role === "ProgramAccountant" || user.role === "Admin"}
      />
    </div>
  );
}
