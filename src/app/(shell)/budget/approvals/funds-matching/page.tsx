import Link from "next/link";
import { Wallet, AlertTriangle, ArrowLeft } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  generateFundsMatching,
  monthlyApprovalKpis,
  type Priority,
} from "@/lib/monthly-approval-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";

const PRIORITY_TONE: Record<Priority, string> = {
  Critical:   "bg-rose-100    text-rose-700",
  High:       "bg-amber-100   text-amber-700",
  Medium:     "bg-sky-100     text-sky-700",
  Low:        "bg-slate-100   text-slate-700",
  Deferrable: "bg-slate-100   text-slate-500",
};

export default function FundsMatchingPage() {
  const rows = generateFundsMatching();
  const k    = monthlyApprovalKpis();
  const totalCritical    = rows.reduce((a, r) => a + r.criticalActivities, 0);
  const totalDeferrable  = rows.reduce((a, r) => a + r.deferrableActivities, 0);

  return (
    <StubPage
      title="Available Funds Matching"
      subtitle="Country Director's reconciliation view. Compare PL-approved monthly requests against available funds, prioritise critical activities, defer low-priority ones."
    >
      <Link
        href="/approvals"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Approvals
      </Link>

      {/* Top KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Total requested"  value={formatUgxBig(k.totalRequested)} tone="edify" />
        <Kpi label="Available funds"  value={formatUgxBig(k.totalAvailable)} tone="green" />
        <Kpi label="Funding gap"      value={formatUgxBig(Math.max(0, k.fundingGap))} tone={k.fundingGap > 0 ? "rose" : "green"} sub={k.fundingGap > 0 ? "Requires prioritisation" : "Fully fundable"} />
        <Kpi label="Critical activities" value={String(totalCritical)} sub={`${totalDeferrable} deferrable`} tone="amber" />
      </section>

      {/* Funding gap recommendation */}
      {k.fundingGap > 0 && (
        <section className="card p-3.5 border-rose-200 bg-rose-50/40">
          <h2 className="text-[13.5px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <AlertTriangle size={13} className="text-rose-700" />
            Funding Gap Detected
          </h2>
          <p className="text-[11.5px] muted mt-1">
            Recommended prioritisation: SSA verification → Core Schools behind package → overdue training follow-ups → high-risk schools.
            Defer low-risk monitoring visits to next month or shift to partner-led delivery.
          </p>
          <ul className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-1.5 text-[12px]">
            <li className="inline-flex items-start gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" /><span>Prioritise critical SSA verification + Core 4+4 visits</span></li>
            <li className="inline-flex items-start gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" /><span>Defer Deferrable + Low-priority activities to next month</span></li>
            <li className="inline-flex items-start gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-sky-500 mt-1.5 shrink-0" /><span>Shift selected visits to partner-led delivery where certified</span></li>
            <li className="inline-flex items-start gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" /><span>Split high-cost trainings across multiple months</span></li>
          </ul>
        </section>
      )}

      {/* Per-submission matching */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Wallet size={14} className="text-[var(--color-edify-primary)]" />
            PL-by-PL matching
          </h2>
          <span className="text-caption muted">{rows.length} submissions</span>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Program Lead</th>
                <th scope="col" className="py-2 px-2">Region</th>
                <th scope="col" className="py-2 px-2 text-right">Requested</th>
                <th scope="col" className="py-2 px-2 text-right">Available</th>
                <th scope="col" className="py-2 px-2 text-right">Gap</th>
                <th scope="col" className="py-2 px-2">Priority</th>
                <th scope="col" className="py-2 px-2 text-right">Critical / Deferrable</th>
                <th scope="col" className="py-2 pl-2">Recommendation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {rows.map((r) => (
                <tr key={r.submissionId} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                  <td className="py-2.5 pr-2 font-extrabold">
                    <Link href={`/budget/approvals/${r.submissionId}`} className="hover:text-[var(--color-edify-primary)]">
                      {r.programLead}
                    </Link>
                  </td>
                  <td className="py-2.5 px-2 muted">{r.region}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{formatUgxBig(r.requested)}</td>
                  <td className="py-2.5 px-2 text-right tabular">{formatUgxBig(r.available)}</td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">
                    <span className={r.gap > 0 ? "text-rose-700" : "text-emerald-700"}>
                      {r.gap > 0 ? formatUgxBig(r.gap) : "—"}
                    </span>
                  </td>
                  <td className="py-2.5 px-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", PRIORITY_TONE[r.priority])}>
                      {r.priority}
                    </span>
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-[11.5px]">
                    <span className="text-rose-700 font-extrabold">{r.criticalActivities}</span> / <span className="text-slate-500">{r.deferrableActivities}</span>
                  </td>
                  <td className="py-2.5 pl-2 text-[11.5px] muted leading-snug max-w-[280px]">{r.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Available Funds source panel — every fund record with provenance */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Available funds sources</h2>
          <span className="text-caption muted">Budgets are never compared against an unexplained number.</span>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {rows.map((r) => (
            <div key={r.submissionId} className="rounded-xl border border-[var(--color-edify-border)] p-3">
              <div className="flex items-baseline justify-between mb-1">
                <div className="text-body font-extrabold tracking-tight">{r.programLead}</div>
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                  r.availableFunds.status === "Confirmed" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
                )}>{r.availableFunds.status}</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                <Fact label="Amount"        value={formatUgxBig(r.availableFunds.amountAvailable)} bold />
                <Fact label="Source"        value={r.availableFunds.source} />
                <Fact label="Currency"      value={r.availableFunds.currency} />
                <Fact label="Month"         value={r.availableFunds.month} />
                {r.availableFunds.restriction && <Fact label="Restriction" value={r.availableFunds.restriction} span2 />}
                <Fact label="Confirmed by"  value={`${r.availableFunds.confirmedBy} · ${r.availableFunds.confirmedAt}`} span2 />
                {r.availableFunds.notes && <Fact label="Notes" value={r.availableFunds.notes} span2 />}
              </div>
            </div>
          ))}
        </div>
      </section>
    </StubPage>
  );
}

function Fact({ label, value, bold, span2 }: { label: string; value: React.ReactNode; bold?: boolean; span2?: boolean }) {
  return (
    <div className={cn("rounded-md bg-[var(--color-edify-soft)]/30 p-2", span2 && "col-span-2")}>
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className={cn("text-[11px] mt-0.5 leading-tight", bold && "font-extrabold tabular text-[12px]")}>{value}</div>
    </div>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub?: string; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[22px] font-extrabold tabular leading-none mt-2">{value}</div>
      {sub && <div className="text-caption muted mt-1">{sub}</div>}
    </div>
  );
}
