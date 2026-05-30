import { notFound } from "next/navigation";
import {
  Wallet,
  User,
  MapPin,
  Calendar,
  Receipt,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import {
  fundRequests,
  fundRequestTotal,
  formatUgx,
  type FundRequest,
} from "@/lib/workflow-mock";

const STATUS_BADGE: Record<FundRequest["status"], { tone: "amber" | "blue" | "violet" | "green"; label: string }> = {
  "Pending Accountant": { tone: "amber",  label: "Pending Accountant" },
  "Pending Director":   { tone: "blue",   label: "Pending Director" },
  "Pending RVP":        { tone: "violet", label: "Pending RVP" },
  "Disbursed":          { tone: "green",  label: "Disbursed" },
};

const STAGES: { key: FundRequest["status"]; label: string }[] = [
  { key: "Pending Accountant", label: "Accountant Review" },
  { key: "Pending Director",   label: "Director Approval" },
  { key: "Pending RVP",        label: "RVP Approval" },
  { key: "Disbursed",          label: "Disbursed" },
];

export default async function FundRequestDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const fr = fundRequests.find((f) => f.id === id);
  if (!fr) return notFound();

  const total = fundRequestTotal(fr);
  const stageIdx = STAGES.findIndex((s) => s.key === fr.status);

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",          href: "/dashboard" },
        { label: "Fund Requests", href: "/fund-requests" },
        { label: `#${fr.id}` },
      ]}
      title={`Fund Request #${fr.id}`}
      subtitle={`${fr.district} · ${fr.staff} · ${fr.month}.`}
      Icon={Wallet}
      badge={STATUS_BADGE[fr.status]}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Total"        value={formatUgx(total)}                  caption="All line items"     Icon={Wallet}   tone="edify"  />
        <DetailKpi label="Line Items"   value={String(fr.lineItems.length)}       caption="Distinct cost rows" Icon={Receipt}  tone="violet" />
        <DetailKpi label="Submitted"    value={fr.submittedOn}                    caption="ISO date"           Icon={Calendar} tone="amber"  />
        <DetailKpi label="Staff"        value={fr.staff}                          caption={fr.district}        Icon={User}     tone="edify"  />
      </section>

      {/* Approval timeline */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Approval Chain</h2>
        <ol className="flex items-center gap-1 overflow-x-auto pb-1">
          {STAGES.map((s, i) => {
            const done = i < stageIdx;
            const current = i === stageIdx;
            const tone = done ? "bg-emerald-500 text-white border-emerald-500" : current ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]" : "bg-white text-[var(--color-edify-muted)] border-[var(--color-edify-border)]";
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
        <p className="text-caption muted mt-2">
          Final approval: Accountant → Country Director → RVP. Disbursement happens after RVP signs.
        </p>
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7 card rounded-2xl overflow-hidden">
          <header className="px-4 pt-3.5 pb-2">
            <h3 className="text-[13px] font-extrabold tracking-tight">Line Items</h3>
          </header>
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-[10px] muted font-bold uppercase tracking-wide border-b border-[#eef2f4]">
                <th scope="col" className="text-left  px-4 py-2">Item</th>
                <th scope="col" className="text-right px-4 py-2">Qty</th>
                <th scope="col" className="text-right px-4 py-2">Rate (UGX)</th>
                <th scope="col" className="text-right px-4 py-2">Subtotal</th>
              </tr>
            </thead>
            <tbody>
              {fr.lineItems.map((li, i) => (
                <tr key={i} className="border-b border-[#eef2f4] last:border-0">
                  <td className="px-4 py-2 font-semibold">{li.item}</td>
                  <td className="px-4 py-2 text-right tabular">{li.qty}</td>
                  <td className="px-4 py-2 text-right tabular muted">{li.rate.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right tabular font-extrabold">{(li.qty * li.rate).toLocaleString()}</td>
                </tr>
              ))}
              <tr className="bg-[var(--color-edify-soft)]/40">
                <td className="px-4 py-2.5 font-extrabold" colSpan={3}>Total</td>
                <td className="px-4 py-2.5 text-right tabular font-extrabold">{total.toLocaleString()}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="col-span-12 md:col-span-5">
          <DetailFacts
            rows={[
              { label: "Request ID",  value: fr.id },
              { label: "Staff",       value: fr.staff },
              { label: "District",    value: <span className="inline-flex items-center gap-1.5"><MapPin size={12} />{fr.district}</span> },
              { label: "Month",       value: fr.month },
              { label: "Submitted",   value: fr.submittedOn },
              { label: "Status",      value: fr.status },
            ]}
          />
        </div>
      </section>
    </EntityDetail>
  );
}
