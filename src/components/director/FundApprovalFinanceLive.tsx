import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequests } from "@/lib/api/surfaces";
import { FundApprovalFinanceSnapshot, FundedNotCompletedLive } from "./FundApprovalFinance";

const fmtUgx = (n: number) =>
  n >= 1_000_000_000 ? `UGX ${(n / 1_000_000_000).toFixed(2)}B`
  : n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M`
  : `UGX ${n.toLocaleString()}`;

export async function FundApprovalFinanceLive() {
  const user = await getCurrentUser();
  const r = await fetchFundRequests(user);
  const requests = r.live ? r.data : [];

  const pending = requests.filter((fr) => fr.status === "submitted" && fr.canReview);
  const rows = pending.map((fr) => ({
    id: fr.id,
    region: fr.scope || fr.periodKey || fr.submittedBy,
    amountLabel: fmtUgx(fr.totalAmount),
    activitiesCovered: fr.activityCount,
    stage: "Review",
    href: `/approvals`,
  }));

  const disbursedNoAccount = requests.filter(
    (fr) => fr.status === "disbursed" && (!fr.accountabilityStatus || fr.accountabilityStatus === "none"),
  );
  const disbursedTotal = disbursedNoAccount.reduce((s, fr) => s + (fr.disbursedAmount ?? fr.totalAmount), 0);

  return (
    <section className="grid grid-cols-12 gap-3 items-stretch [&>div>*]:h-full">
      <div className="col-span-12 lg:col-span-8">
        <FundApprovalFinanceSnapshot pendingFundRequests={rows} live />
      </div>
      <div className="col-span-12 lg:col-span-4">
        <FundedNotCompletedLive
          openCount={disbursedNoAccount.length}
          totalLabel={fmtUgx(disbursedTotal)}
          activityCount={disbursedNoAccount.reduce((s, fr) => s + fr.activityCount, 0)}
        />
      </div>
    </section>
  );
}
