import { notFound } from "next/navigation";
import { Wallet, User, Calendar, Receipt, AlertTriangle } from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { getCurrentUser } from "@/lib/auth";
import { fetchFundRequest, type BeFundRequest } from "@/lib/api/surfaces";

export const dynamic = "force-dynamic";

const STATUS_BADGE: Record<BeFundRequest["status"], { tone: "amber" | "blue" | "green" | "rose" | "slate"; label: string }> = {
  submitted: { tone: "amber", label: "Submitted" },
  approved:  { tone: "blue",  label: "Approved" },
  disbursed: { tone: "green", label: "Disbursed" },
  returned:  { tone: "rose",  label: "Returned" },
  rejected:  { tone: "slate", label: "Rejected" },
};

// Single-stage money chain (backend-canonical): the planner submits, their
// Program Lead reviews, the accountant disburses.
const STAGES = [
  { key: "submitted", label: "Submitted" },
  { key: "approved",  label: "PL Review" },
  { key: "disbursed", label: "Disbursed" },
] as const;

const fmtUgx = (n: number) => `UGX ${Math.round(n || 0).toLocaleString()}`;

export default async function FundRequestDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  const res = await fetchFundRequest(user, id);
  if (!res.live) return notFound();
  const fr = res.data;

  const stageIdx = fr.status === "disbursed" ? 2 : fr.status === "approved" ? 1 : 0;
  const offPath = fr.status === "returned" || fr.status === "rejected";
  const activities = fr.breakdown?.activities ?? [];
  const total = fr.totalAmount || fr.breakdown?.total || 0;
  const anyMissing = activities.some((a) => a.costMissing);

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",          href: "/dashboard" },
        { label: "Fund Requests", href: "/fund-requests" },
        { label: fr.period },
      ]}
      title={`Fund Request · ${fr.period}`}
      subtitle={`${fr.scope} · ${fr.submittedBy} (${fr.submittedByRole}) · ${fr.fy}.`}
      Icon={Wallet}
      badge={STATUS_BADGE[fr.status]}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Total"      value={fmtUgx(total)}                  caption="All activities"   Icon={Wallet}   tone="edify"  />
        <DetailKpi label="Activities" value={String(fr.activityCount)}       caption="In this request"  Icon={Receipt}  tone="violet" />
        <DetailKpi label="Period"     value={fr.period}                      caption={fr.fy}            Icon={Calendar} tone="amber"  />
        <DetailKpi label="Submitted"  value={(fr.createdAt || "").slice(0, 10)} caption={fr.submittedByRole} Icon={User} tone="edify" />
      </section>

      {/* Approval chain — single-stage (Submit → PL review → Disburse). */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Approval Chain</h2>
        {offPath ? (
          <div className="flex items-center gap-2 text-[12px] font-bold text-rose-600">
            <AlertTriangle size={14} /> {fr.status === "returned" ? "Returned to submitter" : "Rejected"}
            {fr.reviewNote ? <span className="font-semibold muted">— {fr.reviewNote}</span> : null}
          </div>
        ) : (
          <ol className="flex items-center gap-1 overflow-x-auto pb-1">
            {STAGES.map((s, i) => {
              const done = i < stageIdx;
              const current = i === stageIdx && fr.status !== "disbursed";
              const tone = done || fr.status === "disbursed"
                ? "bg-emerald-500 text-white border-emerald-500"
                : current
                ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                : "bg-white text-[var(--color-edify-muted)] border-[var(--color-edify-border)]";
              return (
                <li key={s.key} className="flex items-center gap-2 shrink-0">
                  <span className={`h-7 px-2.5 rounded-full text-[11px] font-extrabold border inline-flex items-center ${tone}`}>
                    {i + 1}. {s.label}
                  </span>
                  {i < STAGES.length - 1 && <span className="text-[var(--color-edify-muted)]">→</span>}
                </li>
              );
            })}
          </ol>
        )}
        <p className="text-caption muted mt-2">
          Submitted by the planner, reviewed by their Program Lead, then disbursed by the accountant. Payment of executed work happens separately and only after IA verification.
        </p>
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7 card rounded-2xl overflow-hidden">
          <header className="px-4 pt-3.5 pb-2 flex items-center justify-between">
            <h3 className="text-[13px] font-extrabold tracking-tight">Costed Activities</h3>
            {anyMissing && (
              <span className="text-[10.5px] font-bold text-amber-600 inline-flex items-center gap-1"><AlertTriangle size={12} /> some costs missing</span>
            )}
          </header>
          {activities.length === 0 ? (
            <p className="px-4 py-3 text-[11.5px] muted">No costed breakdown available for this request.</p>
          ) : (
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-[10px] muted font-bold uppercase tracking-wide border-b border-[#eef2f4]">
                  <th scope="col" className="text-left  px-4 py-2">Activity</th>
                  <th scope="col" className="text-left  px-4 py-2">Delivery</th>
                  <th scope="col" className="text-right px-4 py-2">Amount (UGX)</th>
                </tr>
              </thead>
              <tbody>
                {activities.map((a) => (
                  <tr key={a.id} className="border-b border-[#eef2f4] last:border-0">
                    <td className="px-4 py-2 font-semibold">{a.activityType.replace(/_/g, " ")}<span className="muted font-normal"> · {a.target}</span></td>
                    <td className="px-4 py-2 muted">{a.deliveryType}</td>
                    <td className="px-4 py-2 text-right tabular font-extrabold">{a.costMissing ? "—" : a.amount.toLocaleString()}</td>
                  </tr>
                ))}
                <tr className="bg-[var(--color-edify-soft)]/40">
                  <td className="px-4 py-2.5 font-extrabold" colSpan={2}>Total</td>
                  <td className="px-4 py-2.5 text-right tabular font-extrabold">{total.toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
        <div className="col-span-12 md:col-span-5">
          <DetailFacts
            rows={[
              { label: "Period",     value: `${fr.period} · ${fr.fy}` },
              { label: "Scope",      value: fr.scope },
              { label: "Submitter",  value: `${fr.submittedBy} (${fr.submittedByRole})` },
              { label: "Status",     value: STATUS_BADGE[fr.status].label },
              ...(fr.disbursedAmount != null ? [{ label: "Disbursed", value: fmtUgx(fr.disbursedAmount) }] : []),
              ...(fr.accountabilityNetsuiteId ? [{ label: "NetSuite ID", value: fr.accountabilityNetsuiteId }] : []),
            ]}
          />
        </div>
      </section>
    </EntityDetail>
  );
}
