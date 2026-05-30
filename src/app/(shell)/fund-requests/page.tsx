import { Wallet } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import {
  fundRequests,
  fundRequestTotal,
  formatUgx,
  type FundRequest,
} from "@/lib/workflow-mock";

const STATUS_TONE: Record<FundRequest["status"], "amber" | "blue" | "violet" | "green"> = {
  "Pending Accountant": "amber",
  "Pending Director":   "blue",
  "Pending RVP":        "violet",
  "Disbursed":          "green",
};

export default function FundRequestsIndex() {
  const total = fundRequests.reduce((a, f) => a + fundRequestTotal(f), 0);

  return (
    <EntityIndex
      title="Fund Requests"
      subtitle="Approval chain: Accountant → Country Director → RVP → Disbursement. Click a request for line items and history."
      Icon={Wallet}
      count={fundRequests.length}
      searchPlaceholder="Search by district, staff, month"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {fundRequests.map((fr) => (
          <IndexRow
            key={fr.id}
            href={`/fund-requests/${fr.id}`}
            Icon={Wallet}
            title={`#${fr.id} · ${fr.district}`}
            subtitle={`${fr.staff} · ${fr.month}`}
            meta={`${fr.lineItems.length} line items · submitted ${fr.submittedOn}`}
            badges={[{ label: fr.status, tone: STATUS_TONE[fr.status] }]}
            rightTop={formatUgx(fundRequestTotal(fr))}
            rightBottom="total"
          />
        ))}
      </section>
      <p className="text-[11.5px] muted text-right">Total in pipeline: {formatUgx(total)}</p>
    </EntityIndex>
  );
}
