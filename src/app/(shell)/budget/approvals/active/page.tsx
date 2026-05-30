import Link from "next/link";
import { ArrowLeft, CheckCircle2, TrendingUp } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  monthlyPlanSubmissions,
  generateFinalApprovedFundingPlan,
  statusTone,
  type Priority,
} from "@/lib/monthly-approval-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";

const TONE = {
  edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  green: "bg-emerald-100 text-emerald-700",
  amber: "bg-amber-100   text-amber-700",
  rose:  "bg-rose-100    text-rose-700",
  violet:"bg-violet-100  text-violet-700",
  sky:   "bg-sky-100     text-sky-700",
  slate: "bg-slate-100   text-slate-700",
} as const;

const PRIORITY_TONE: Record<Priority, string> = {
  Critical:   "bg-rose-100    text-rose-700",
  High:       "bg-amber-100   text-amber-700",
  Medium:     "bg-sky-100     text-sky-700",
  Low:        "bg-slate-100   text-slate-700",
  Deferrable: "bg-slate-100   text-slate-500",
};

export default function ActiveFundingPlanPage() {
  const active = monthlyPlanSubmissions.filter((s) =>
    s.status === "Final Approved" || s.status === "Active Funding Plan" || s.status === "Disbursed"
  );
  const totalActive = active.reduce((a, s) => a + (s.finalApprovedBudget ?? s.amendedBudget ?? s.requestedBudget), 0);
  const totalDisbursed = active.reduce((a, s) => a + (s.disbursement?.disbursedAmount ?? 0), 0);
  const totalSpent     = active.reduce((a, s) => a + (s.disbursement?.spentAmount     ?? 0), 0);
  const totalVerified  = active.reduce((a, s) => a + (s.disbursement?.verifiedCompletedValue ?? 0), 0);

  return (
    <StubPage
      title="Active Monthly Funding Plans"
      subtitle="Final-approved plans flowing into disbursement. Each plan carries a funding source, week-by-week disbursement schedule, and live utilisation tracking."
    >
      <Link
        href="/approvals"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Approvals
      </Link>

      {/* Headline KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Active plans"      value={String(active.length)}            tone="green"  />
        <Kpi label="Approved value"    value={formatUgxBig(totalActive)}        tone="green"  />
        <Kpi label="Disbursed"         value={formatUgxBig(totalDisbursed)}     tone="amber"  />
        <Kpi label="Verified completed" value={formatUgxBig(totalVerified)}     tone={totalVerified < totalSpent * 0.8 ? "rose" : "green"} sub={`${formatUgxBig(totalSpent)} spent`} />
      </section>

      {/* Final Approved Monthly Funding Plan — full artifact per submission */}
      {active.map((s) => {
        const plan = generateFinalApprovedFundingPlan(s);
        if (!plan) return null;
        return (
          <article key={s.id} className="card p-3.5 border-emerald-200 bg-emerald-50/40">
            <header className="flex items-baseline justify-between mb-2">
              <div>
                <h2 className="text-[14.5px] font-extrabold tracking-tight inline-flex items-center gap-2">
                  <CheckCircle2 size={14} className="text-emerald-700" />
                  <Link href={`/budget/approvals/${s.id}`} className="hover:text-[var(--color-edify-primary)]">
                    {plan.programLead} · {plan.region}
                  </Link>
                </h2>
                <div className="text-caption muted">{plan.month} · {plan.approvedActivities.length} approved activities</div>
              </div>
              <span className={cn("inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold whitespace-nowrap", TONE[statusTone(s.status)])}>
                {s.status}
              </span>
            </header>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px] mb-3">
              <Fact label="Approved budget" value={formatUgxBig(plan.approvedBudget)} bold tone="green" />
              <Fact label="Funding source"  value={plan.fundingSource} />
              <Fact label="Amendments"      value={plan.amendmentSummary.count === 0 ? "—" : `${plan.amendmentSummary.count} (net ${plan.amendmentSummary.netDelta < 0 ? "-" : "+"}${formatUgxBig(Math.abs(plan.amendmentSummary.netDelta))})`} />
              <Fact label="Priority"        value={<span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-caption font-extrabold", PRIORITY_TONE[s.priority])}>{s.priority}</span>} />
            </div>

            {plan.fundingSourceNote && (
              <div className="text-[11.5px] muted mb-2">
                <span className="font-extrabold text-[var(--color-edify-text)]">Source note: </span>
                {plan.fundingSourceNote}
              </div>
            )}

            {/* Week-by-week disbursement schedule */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
              {plan.disbursementSchedule.map((d) => (
                <div key={d.week} className="rounded-xl bg-white border border-[var(--color-edify-border)] p-2.5">
                  <div className="text-caption muted font-extrabold uppercase tracking-wide">Week {d.week}</div>
                  <div className="text-body-lg font-extrabold tabular leading-none mt-1">{formatUgxBig(d.amount)}</div>
                </div>
              ))}
            </div>

            {/* Disbursement utilization */}
            {s.disbursement && (
              <div className="mt-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3">
                <h3 className="text-[12px] font-extrabold tracking-tight uppercase muted mb-2 inline-flex items-center gap-2">
                  <TrendingUp size={12} />
                  Utilisation
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                  <Fact label="Disbursed"           value={formatUgxBig(s.disbursement.disbursedAmount)} bold />
                  <Fact label="Spent"               value={formatUgxBig(s.disbursement.spentAmount)}     bold />
                  <Fact label="Verified completed"  value={formatUgxBig(s.disbursement.verifiedCompletedValue)} bold />
                  <Fact label="Unused"              value={formatUgxBig(s.disbursement.unusedAmount)} />
                </div>
              </div>
            )}

            {/* Conditions */}
            {plan.conditions.length > 0 && (
              <div className="mt-3">
                <div className="text-caption font-extrabold uppercase tracking-wide muted mb-1">Approval conditions</div>
                <ul className="space-y-0.5 text-[11.5px]">
                  {plan.conditions.map((c) => (
                    <li key={c.id} className="inline-flex items-start gap-1.5">
                      <span className={cn(
                        "h-1.5 w-1.5 rounded-full mt-1.5 shrink-0",
                        c.status === "Met"    ? "bg-emerald-500" :
                        c.status === "Open"   ? "bg-amber-500"   :
                                                "bg-slate-400",
                      )} />
                      <span>{c.text} <span className="muted">({c.status})</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Program Accountant next steps */}
            <div className="mt-3">
              <div className="text-caption font-extrabold uppercase tracking-wide muted mb-1">Program Accountant next steps</div>
              <ul className="space-y-0.5 text-[11.5px]">
                {plan.programAccountantNextSteps.map((n, i) => (
                  <li key={i} className="inline-flex items-start gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
                    {n}
                  </li>
                ))}
              </ul>
            </div>
          </article>
        );
      })}

      {active.length === 0 && (
        <section className="card rounded-2xl p-6 text-center">
          <h2 className="text-body-lg font-extrabold tracking-tight">No active funding plans yet</h2>
          <p className="text-[11.5px] muted mt-1">Plans land here once the RVP grants final approval.</p>
        </section>
      )}

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Disbursement contract: </span>
        Once a plan is Final Approved, the Program Accountant releases funds per the week-by-week schedule
        above. Variance above 10% requires CD review. Reallocations require re-filing through the workflow.
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub?: string; tone?: keyof typeof TONE }) {
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[22px] font-extrabold tabular leading-none mt-2">{value}</div>
      {sub && <div className="text-caption muted mt-1">{sub}</div>}
    </div>
  );
}

function Fact({ label, value, bold, tone }: { label: string; value: React.ReactNode; bold?: boolean; tone?: "green" }) {
  const TONE_TEXT = { green: "text-emerald-700" } as const;
  return (
    <div className="rounded-md bg-[var(--color-edify-soft)]/30 p-2">
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className={cn("text-[11px] mt-0.5 leading-tight", bold && "font-extrabold tabular text-body", tone && TONE_TEXT[tone])}>{value}</div>
    </div>
  );
}
