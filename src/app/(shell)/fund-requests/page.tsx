import { Wallet } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequests, type BeFundRequest } from "@/lib/api/surfaces";

// Fund Requests index — the live monthly fund-request pipeline. Reads the
// caller's scoped requests from the backend (single-stage chain: a planner
// submits → their Program Lead reviews → the accountant disburses). The old
// page rendered workflow-mock rows and advertised a 3-stage Accountant→CD→RVP
// chain that contradicted the backend; both are gone.
export const dynamic = "force-dynamic";

const STATUS_TONE: Record<BeFundRequest["status"], "amber" | "blue" | "green" | "rose" | "slate"> = {
  submitted: "amber",
  approved:  "blue",
  disbursed: "green",
  returned:  "rose",
  rejected:  "slate",
};
const STATUS_LABEL: Record<BeFundRequest["status"], string> = {
  submitted: "Submitted",
  approved:  "Approved",
  disbursed: "Disbursed",
  returned:  "Returned",
  rejected:  "Rejected",
};

const fmtUgx = (n: number) => `UGX ${Math.round(n || 0).toLocaleString()}`;

export default async function FundRequestsIndex() {
  const user = await getCurrentUser();
  const res = await fetchFundRequests(user);
  const rows = res.live ? res.data : [];
  const total = rows.reduce((a, f) => a + (f.totalAmount || 0), 0);

  return (
    <EntityIndex
      title="Fund Requests"
      subtitle="Approval chain: Submit → Program Lead review → Disbursement. Click a request for its costed breakdown."
      Icon={Wallet}
      count={rows.length}
      searchPlaceholder="Search by period, scope, submitter"
    >
      {rows.length === 0 ? (
        <div className="card rounded-2xl p-6 text-center text-[12.5px] muted">
          No fund requests in the pipeline yet — they appear here once a planner generates a monthly request from their scheduled work.
        </div>
      ) : (
        <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
          {rows.map((fr) => (
            <IndexRow
              key={fr.id}
              href={`/fund-requests/${fr.id}`}
              Icon={Wallet}
              title={`${fr.period} · ${fr.scope}`}
              subtitle={`${fr.submittedBy} · ${fr.submittedByRole}`}
              meta={`${fr.activityCount} ${fr.activityCount === 1 ? "activity" : "activities"} · ${fr.fy}`}
              badges={[{ label: STATUS_LABEL[fr.status], tone: STATUS_TONE[fr.status] }]}
              rightTop={fmtUgx(fr.totalAmount)}
              rightBottom="total"
            />
          ))}
        </section>
      )}
      {rows.length > 0 && (
        <p className="text-[11.5px] muted text-right">Total in pipeline: {fmtUgx(total)}</p>
      )}
    </EntityIndex>
  );
}
