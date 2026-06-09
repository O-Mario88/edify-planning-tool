import Link from "next/link";
import { ArrowLeft, Send, CheckCircle2, RotateCcw, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  monthlyPlanSubmissions,
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

export default function RvpFinalApprovalQueuePage() {
  const queue   = monthlyPlanSubmissions.filter((s) => s.status === "Submitted to RVP");
  const pending = monthlyPlanSubmissions.filter((s) => s.status === "Approved by Country Director");
  const passed  = monthlyPlanSubmissions.filter((s) =>
    s.status === "Approved by RVP" || s.status === "Final Approved" || s.status === "Active Funding Plan" || s.status === "Disbursed"
  );

  const totalQueued = queue.reduce((a, s) => a + (s.amendedBudget ?? s.requestedBudget), 0);

  return (
    <StubPage
      title="RVP Final Approval Queue"
      subtitle="CD-approved monthly plans awaiting Regional VP final sign-off. Only the RVP may final-approve. Returns send the plan back to CD for re-work."
    >
      <Link
        href="/approvals"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Approvals
      </Link>

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Kpi label="In RVP queue"          value={String(queue.length)}   sub={formatUgxBig(totalQueued)}  tone="violet" />
        <Kpi label="CD-approved (next up)" value={String(pending.length)} sub="Will land in queue next"     tone="amber"  />
        <Kpi label="Already final-approved" value={String(passed.length)} sub="Active or moving to active" tone="green"  />
      </section>

      {/* Active queue */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2 inline-flex items-center gap-2">
          <Send size={14} className="text-violet-600" />
          Awaiting final approval
        </h2>
        {queue.length === 0 ? (
          <div className="text-[12px] muted">No submissions currently in the RVP queue.</div>
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {queue.map((s) => (
              <li key={s.id} className="py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <Link href={`/budget/approvals/${s.id}`} className="text-[13px] font-extrabold tracking-tight hover:text-[var(--color-edify-primary)]">
                    {s.programLeadName} · {s.region}
                  </Link>
                  <div className="text-caption muted">
                    {s.monthLabel} · {s.activities.length} activities · CD-approved
                  </div>
                </div>
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0", PRIORITY_TONE[s.priority])}>
                  {s.priority}
                </span>
                <div className="w-[140px] text-right tabular font-extrabold shrink-0">
                  {formatUgxBig(s.amendedBudget ?? s.requestedBudget)}
                </div>
                <div className="hidden md:flex items-center gap-1.5 shrink-0">
                  <button type="button" className="h-8 px-2.5 rounded-md bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11px] font-semibold inline-flex items-center gap-1">
                    <CheckCircle2 size={11} />
                    Final approve
                  </button>
                  <button type="button" className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold inline-flex items-center gap-1">
                    <RotateCcw size={11} />
                    Return to CD
                  </button>
                </div>
                <Link href={`/budget/approvals/${s.id}`} className="h-8 w-8 rounded-md border border-[var(--color-edify-border)] grid place-items-center hover:bg-[var(--color-edify-soft)]/40 shrink-0">
                  <ChevronRight size={12} className="text-[var(--color-edify-muted)]" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Pending → next up */}
      {pending.length > 0 && (
        <section className="card p-3.5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Next up — CD-approved, awaiting CD submission to RVP</h2>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {pending.map((s) => (
              <li key={s.id} className="py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <Link href={`/budget/approvals/${s.id}`} className="text-body font-extrabold tracking-tight hover:text-[var(--color-edify-primary)]">
                    {s.programLeadName} · {s.region}
                  </Link>
                  <div className="text-caption muted">{s.monthLabel} · {formatUgxBig(s.amendedBudget ?? s.requestedBudget)}</div>
                </div>
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", TONE[statusTone(s.status)])}>
                  {s.status}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </StubPage>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub: string; tone?: keyof typeof TONE }) {
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[26px] font-extrabold tabular leading-none mt-2">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}
