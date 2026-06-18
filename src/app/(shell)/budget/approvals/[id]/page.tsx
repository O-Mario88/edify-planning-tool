import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle2,
  RotateCcw,
  Send,
  History,
  Wallet,
  Edit3,
  ShieldCheck,
  Info,
  ClipboardCheck,
  TrendingUp,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { ApprovalActionsClient } from "@/components/demo/ApprovalActionsClient";
import { SubmissionOverlayBanner } from "@/components/demo/SubmissionOverlay";
import {
  getMonthlySubmission,
  getAvailableFunds,
  generateDecisionImpactPreview,
  generateFinalApprovedFundingPlan,
  PRIORITY_FACTOR_LABEL,
  statusTone,
  type Priority,
  type ApprovalStatus,
} from "@/lib/monthly-approval-mock";
import { formatUgxBig } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";

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

export default async function ApprovalSubmissionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!isMockAllowed())
    return (
      <ProductiveEmptyState
        Icon={CheckCircle2}
        tone="info"
        title="This approval submission isn't connected to the live approval chain yet"
        description="The submission detail, budget summary, and audit trail are withheld until they trace to live FundRequest records."
        actionLabel="Open approvals"
        actionHref="/budget/approvals"
        links={[{ label: "Budget", href: "/budget" }]}
        note="No fabricated money figures are shown."
      />
    );
  const s = getMonthlySubmission(id);
  if (!s) return notFound();
  const me = await getCurrentUser();

  // Role + status gate — UI hides actions when role or status don't match.
  // The same check runs server-side via assertCanApproveSubmission() so
  // bypassing the UI cannot trigger an unauthorised approval.
  const isPL    = me.role === "CountryProgramLead";
  const isCD    = me.role === "CountryDirector" || me.role === "Admin";
  const isRVP   = me.role === "RVP";

  const showPlActions  = isPL  && s.status === "Submitted to Program Lead";
  const showCdActions  = isCD  && (s.status === "Submitted to Country Director" || s.status === "Amended by Country Director");
  const showRvpActions = isRVP && (s.status === "Submitted to RVP" || s.status === "Amended by RVP");

  const af = getAvailableFunds(s.availableFundsRecordId);
  const fundingPlan = generateFinalApprovedFundingPlan(s);

  // Pre-compute Decision Impact Preview for a representative 15% reduction —
  // production wires this to the amendment modal's amount input.
  const sampleReduction = Math.round((s.amendedBudget ?? s.requestedBudget) * 0.85);
  const impact = generateDecisionImpactPreview(s, sampleReduction);

  return (
    <StubPage
      title={`${s.programLeadName} · ${s.monthLabel}`}
      subtitle={`${s.region} region · ${s.activities.length} planned activities · Priority ${s.priority}`}
    >
      <Link
        href="/approvals"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Approvals
      </Link>

      {/* Status strip + budget summary */}
      <section className="grid grid-cols-12 gap-3 items-start">
        <div className="card p-3.5 col-span-12 md:col-span-7">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight">Status</h2>
            <span className={cn("inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold whitespace-nowrap", TONE[statusTone(s.status)])}>
              {s.status}
            </span>
          </header>
          <StageBar status={s.status} />
          <div className="mt-3 text-caption muted">Last action: <span className="font-extrabold text-[var(--color-edify-text)]">{s.lastAction}</span></div>
        </div>

        <div className="card p-3.5 col-span-12 md:col-span-5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Budget summary</h2>
          <ul className="space-y-1.5 text-[12px]">
            <Row label="Requested (immutable)" value={formatUgxBig(s.requestedBudget)} strike={s.amendedBudget != null} />
            {s.amendedBudget != null && (
              <Row label="Amended by CD/RVP" value={formatUgxBig(s.amendedBudget)} bold tone="amber" />
            )}
            {s.finalApprovedBudget != null && (
              <Row label="Final Approved" value={formatUgxBig(s.finalApprovedBudget)} bold tone="green" />
            )}
            <Row label="Available allocation" value={formatUgxBig(s.availableAllocation)} />
            <Row label="Funding gap"
                 value={s.fundingGap > 0 ? formatUgxBig(s.fundingGap) : "—"}
                 tone={s.fundingGap > 0 ? "rose" : "green"} />
            <Row label="Priority" value={s.priority} pill={PRIORITY_TONE[s.priority]} />
          </ul>
        </div>
      </section>

      {/* Funding Gap banner */}
      {s.fundingGap > 0 && (
        <section className="card p-3.5 border-rose-200 bg-rose-50/40">
          <div className="flex items-start gap-3">
            <span className="h-9 w-9 rounded-md bg-rose-100 text-rose-700 grid place-items-center shrink-0"><AlertTriangle size={16} /></span>
            <div className="flex-1 min-w-0">
              <h3 className="text-[13.5px] font-extrabold tracking-tight">Funding Gap Detected</h3>
              <p className="text-[11.5px] muted mt-0.5">
                The requested monthly budget exceeds the available funds. Review the recommended
                prioritisation before approving, amending, or sending back this submission.
              </p>
              <ol className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-3 gap-y-1 text-[11.5px] list-decimal list-inside">
                <li>Prioritise SSA verification</li>
                <li>Protect Core School 4+4 activities</li>
                <li>Prioritise overdue training follow-ups</li>
                <li>Protect high-risk schools</li>
                <li>Defer low-risk monitoring visits</li>
                <li>Shift eligible activities to certified partner-led delivery</li>
                <li>Split lower-priority activities across future months</li>
              </ol>
            </div>
          </div>
        </section>
      )}

      {/* Available Funds Panel */}
      {af && (
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <Wallet size={14} className="text-[var(--color-edify-primary)]" />
              Available funds
            </h2>
            <span className={cn(
              "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
              af.status === "Confirmed" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
            )}>{af.status}</span>
          </header>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
            <Fact label="Amount available"  value={formatUgxBig(af.amountAvailable)} bold />
            <Fact label="Source"             value={af.source} />
            <Fact label="Currency"           value={af.currency} />
            <Fact label="Confirmed by"       value={`${af.confirmedBy} · ${af.confirmedAt}`} />
            {af.restriction && <Fact label="Restriction" value={af.restriction} span2 />}
            {af.notes       && <Fact label="Notes"       value={af.notes}        span2 />}
          </div>
        </section>
      )}

      {/* Priority "Why?" */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Info size={14} className="text-[var(--color-edify-primary)]" />
            Why this priority?
          </h2>
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-caption font-extrabold", PRIORITY_TONE[s.priority])}>
            {s.priority}
          </span>
        </header>
        {s.priorityFactors.length === 0 ? (
          <div className="text-[11.5px] muted">No specific drivers — routine workload.</div>
        ) : (
          <ul className="space-y-1.5 text-[12px]">
            {s.priorityFactors.map((f, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                <span>
                  <span className="font-extrabold">{PRIORITY_FACTOR_LABEL[f.kind]} — </span>
                  <span className="muted">{f.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Per-role actions */}
      {(showPlActions || showCdActions || showRvpActions) && (
        <section className="card p-3.5 border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/40">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2">
            {showPlActions  && "Program Lead — Review plan + proposed budget"}
            {showCdActions  && "Country Director — Approve, amend, or return"}
            {showRvpActions && "RVP — Final approval"}
          </h2>
          {showPlActions && (
            <p className="text-[11.5px] muted mb-3">
              Confirm activities reflect recommendations, SSA-informed plans are prioritised, Core 4+4 packages are
              aligned, cluster dates are present, and workload is realistic. <span className="font-extrabold">PL approval
              is for plan + proposed budget only — funds are not finalised here.</span>
            </p>
          )}
          {showCdActions && (
            <p className="text-[11.5px] muted mb-3">
              Compare {formatUgxBig(s.requestedBudget)} requested against {formatUgxBig(s.availableAllocation)} available.
              {s.fundingGap > 0 && ` Gap: ${formatUgxBig(s.fundingGap)}. `}
              Amendments require a reason; the original budget is preserved permanently.
            </p>
          )}
          {showRvpActions && (
            <p className="text-[11.5px] muted mb-3">
              Final approval. Confirm strategic alignment, Core obligations, and target risk. Once approved, the
              monthly funding plan becomes active and the Program Accountant prepares disbursement.
            </p>
          )}
          <ApprovalActionsClient
            submissionId={s.id}
            stage={showPlActions ? "Program Lead" : showCdActions ? "Country Director" : "RVP"}
            requestedBudget={s.requestedBudget}
            amendedBudget={s.amendedBudget}
          />

          {/* Decision Impact Preview — surfaces what an amendment would do */}
          {(showCdActions || showRvpActions) && (
            <DecisionImpactPanel impact={impact} sampleReduction={sampleReduction} originalBudget={s.amendedBudget ?? s.requestedBudget} />
          )}
        </section>
      )}

      {/* Program Accountant Review Note */}
      {s.accountantNote && (
        <section className="card p-3.5 border-sky-200 bg-sky-50/40">
          <header className="flex items-baseline justify-between mb-1">
            <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <ClipboardCheck size={14} className="text-sky-700" />
              Finance review note
            </h2>
            <span className="text-caption muted">{s.accountantNote.reviewedBy} · {s.accountantNote.reviewedAt}</span>
          </header>
          <div className="flex items-center gap-3 text-[11px] muted mb-2">
            <span className="inline-flex items-center gap-1">
              {s.accountantNote.availableFundsConfirmed
                ? <CheckCircle2 size={11} className="text-emerald-600" />
                : <AlertTriangle size={11} className="text-rose-700" />}
              Available funds {s.accountantNote.availableFundsConfirmed ? "confirmed" : "NOT confirmed"}
            </span>
            <span className="inline-flex items-center gap-1">
              {s.accountantNote.costSettingsConfirmed
                ? <CheckCircle2 size={11} className="text-emerald-600" />
                : <AlertTriangle size={11} className="text-rose-700" />}
              Cost settings {s.accountantNote.costSettingsConfirmed ? "valid" : "outdated"}
            </span>
          </div>
          <p className="text-[12px] leading-snug">{s.accountantNote.notes}</p>
          {s.accountantNote.budgetErrors.length > 0 && (
            <div className="mt-2">
              <div className="text-caption font-extrabold uppercase tracking-wide text-rose-700 mb-1">Errors flagged</div>
              <ul className="text-[11.5px] space-y-0.5">
                {s.accountantNote.budgetErrors.map((e, i) => (
                  <li key={i} className="inline-flex items-start gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                    {e}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* Activity table */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Planned activities</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Week</th>
                <th scope="col" className="py-2 px-2">Activity</th>
                <th scope="col" className="py-2 px-2">School / Cluster</th>
                <th scope="col" className="py-2 px-2">District</th>
                <th scope="col" className="py-2 px-2 text-right">Qty</th>
                <th scope="col" className="py-2 px-2 text-right">Unit cost</th>
                <th scope="col" className="py-2 px-2 text-right">Total</th>
                <th scope="col" className="py-2 pl-2">Priority / Linkage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {s.activities.map((a) => (
                <tr key={a.id}>
                  <td className="py-2 pr-2 font-extrabold tabular">W{a.week}</td>
                  <td className="py-2 px-2">
                    <div className="font-extrabold tracking-tight">{a.type}</div>
                    <div className="text-caption muted">{a.rationale}</div>
                  </td>
                  <td className="py-2 px-2 muted">{a.schoolName ?? a.cluster ?? "—"}</td>
                  <td className="py-2 px-2 muted">{a.district ?? "—"}</td>
                  <td className="py-2 px-2 text-right tabular">{a.quantity}</td>
                  <td className="py-2 px-2 text-right tabular">{formatUgxBig(a.unitCost)}</td>
                  <td className="py-2 px-2 text-right tabular font-extrabold">{formatUgxBig(a.totalCost)}</td>
                  <td className="py-2 pl-2">
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", PRIORITY_TONE[a.priority])}>
                      {a.priority}
                    </span>
                    {a.ssaUrgent   && <div className="text-[9.5px] text-rose-700 font-extrabold mt-0.5">SSA URGENT</div>}
                    {a.corePackage && <div className="text-[9.5px] text-emerald-700 font-extrabold mt-0.5">Core 4+4</div>}
                    {a.partnerLed  && <div className="text-[9.5px] text-violet-700 font-extrabold mt-0.5">Partner-led</div>}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-[var(--color-edify-border)]">
                <td colSpan={6} className="py-2 pr-2 text-right font-extrabold">Total requested (immutable)</td>
                <td className="py-2 px-2 text-right tabular font-extrabold">{formatUgxBig(s.requestedBudget)}</td>
                <td />
              </tr>
              {s.amendedBudget != null && (
                <tr>
                  <td colSpan={6} className="py-1 pr-2 text-right text-amber-700 font-extrabold">After amendment</td>
                  <td className="py-1 px-2 text-right tabular font-extrabold text-amber-700">{formatUgxBig(s.amendedBudget)}</td>
                  <td />
                </tr>
              )}
            </tfoot>
          </table>
        </div>
      </section>

      {/* Approval Conditions */}
      {s.approvalConditions.length > 0 && (
        <section className="card p-3.5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2 inline-flex items-center gap-2">
            <ShieldCheck size={14} className="text-violet-700" />
            Approval conditions
          </h2>
          <ul className="space-y-2">
            {s.approvalConditions.map((c) => (
              <li key={c.id} className="rounded-xl border border-[var(--color-edify-border)] p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight">{c.text}</div>
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                    c.status === "Open"   && "bg-amber-100   text-amber-700",
                    c.status === "Met"    && "bg-emerald-100 text-emerald-700",
                    c.status === "Waived" && "bg-slate-100   text-slate-700",
                  )}>{c.status}</span>
                </div>
                <div className="text-caption muted mt-0.5">
                  Added by {c.addedBy} ({c.addedByRole}) · {c.addedAt}{c.assignedTo ? ` · assigned to ${c.assignedTo}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Amendment history */}
      {s.amendments.length > 0 && (
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <History size={14} className="text-amber-600" />
              Amendment history (append-only)
            </h2>
            <span className="text-caption muted">{s.amendments.length} amendment(s)</span>
          </header>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {s.amendments.map((a) => (
              <li key={a.id} className="py-2.5">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight">{a.approvalStage} · {a.amendedBy} ({a.amendedByRole})</div>
                  <div className="text-caption muted">{a.amendedAt}</div>
                </div>
                <div className="text-[11.5px] mt-0.5">
                  <span className="muted line-through">{formatUgxBig(a.originalAmount)}</span>
                  <span className="mx-2">→</span>
                  <span className="font-extrabold">{formatUgxBig(a.amendedAmount)}</span>
                  <span className={cn("ml-2 font-extrabold", a.difference < 0 ? "text-rose-700" : "text-emerald-700")}>
                    ({a.difference < 0 ? "" : "+"}{formatUgxBig(Math.abs(a.difference))})
                  </span>
                </div>
                <div className="text-[11.5px] muted leading-snug mt-1">{a.reason}</div>
                {a.comment && (
                  <div className="text-caption muted italic mt-1">&quot;{a.comment}&quot;</div>
                )}
                <div className="text-caption muted mt-1">
                  Affected: {a.affectedActivities.join(", ")}
                  {a.affectedDistricts && a.affectedDistricts.length > 0 && ` · Districts: ${a.affectedDistricts.join(", ")}`}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Disbursement tracking — only once funds are flowing */}
      {s.disbursement && (
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <TrendingUp size={14} className="text-emerald-600" />
              Disbursement &amp; utilization
            </h2>
            <span className="text-caption muted">Updated by {s.disbursement.lastUpdatedBy} · {s.disbursement.lastUpdatedAt}</span>
          </header>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
            <Fact label="Approved"            value={formatUgxBig(s.disbursement.approvedAmount)}    bold />
            <Fact label="Disbursed"           value={formatUgxBig(s.disbursement.disbursedAmount)}   bold />
            <Fact label="Spent"               value={formatUgxBig(s.disbursement.spentAmount)}      bold />
            <Fact label="Verified completed"  value={formatUgxBig(s.disbursement.verifiedCompletedValue)} bold />
            <Fact label="Unused"              value={formatUgxBig(s.disbursement.unusedAmount)} />
            <Fact label="Returned"            value={formatUgxBig(s.disbursement.returnedAmount)} />
            <Fact label="Variance"            value={formatUgxBig(s.disbursement.variance)} />
          </div>
        </section>
      )}

      {/* Final Approved Monthly Funding Plan output */}
      {fundingPlan && (
        <section className="card p-3.5 border-emerald-200 bg-emerald-50/40">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
              <CheckCircle2 size={14} className="text-emerald-700" />
              Final Approved Monthly Funding Plan
            </h2>
            <span className="text-caption muted">{fundingPlan.month}</span>
          </header>
          <div className="text-[12px] mb-2">
            <span className="font-extrabold">Approved budget: </span>
            <span className="text-body-lg font-extrabold tabular text-emerald-700">{formatUgxBig(fundingPlan.approvedBudget)}</span>
            {fundingPlan.amendmentSummary.count > 0 && (
              <span className="muted ml-2">
                · {fundingPlan.amendmentSummary.count} amendment(s)
                {fundingPlan.amendmentSummary.netDelta !== 0 &&
                  ` (net ${fundingPlan.amendmentSummary.netDelta > 0 ? "+" : "-"}${formatUgxBig(Math.abs(fundingPlan.amendmentSummary.netDelta))})`}
              </span>
            )}
          </div>
          <div className="text-[11.5px] muted mb-2">
            Funding source: <span className="font-extrabold text-[var(--color-edify-text)]">{fundingPlan.fundingSource}</span>
            {fundingPlan.fundingSourceNote && <> · {fundingPlan.fundingSourceNote}</>}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
            {fundingPlan.disbursementSchedule.map((d) => (
              <div key={d.week} className="rounded-xl bg-white border border-[var(--color-edify-border)] p-2.5">
                <div className="text-caption muted font-extrabold uppercase tracking-wide">Week {d.week}</div>
                <div className="text-body-lg font-extrabold tabular leading-none mt-1">{formatUgxBig(d.amount)}</div>
              </div>
            ))}
          </div>
          <div className="mt-3">
            <div className="text-caption font-extrabold uppercase tracking-wide muted mb-1">Program Accountant next steps</div>
            <ul className="space-y-0.5 text-[11.5px]">
              {fundingPlan.programAccountantNextSteps.map((n, i) => (
                <li key={i} className="inline-flex items-start gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
                  {n}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {/* Live demo overlay — shows any actions taken during this session */}
      <SubmissionOverlayBanner submissionId={s.id} />

      {/* Audit trail */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Approval audit trail</h2>
        <ul className="space-y-2">
          {s.audit.map((e, i) => (
            <li key={i} className="flex items-start gap-3 text-[12px]">
              <span className={cn(
                "h-7 w-7 rounded-full grid place-items-center shrink-0",
                e.action === "Approved"        && "bg-emerald-100 text-emerald-700",
                e.action === "Submitted"       && "bg-sky-100     text-sky-700",
                e.action === "Returned"        && "bg-rose-100    text-rose-700",
                e.action === "Amended"         && "bg-amber-100   text-amber-700",
                e.action === "Activated"       && "bg-emerald-100 text-emerald-700",
                e.action === "Disbursed"       && "bg-emerald-100 text-emerald-700",
                e.action === "Closed"          && "bg-slate-100   text-slate-700",
                e.action === "Accountant Note" && "bg-sky-100     text-sky-700",
                (e.action === "Submitted to CD" || e.action === "Submitted to RVP") && "bg-sky-100 text-sky-700",
              )}>
                {e.action === "Approved" || e.action === "Activated" || e.action === "Disbursed"
                  ? <CheckCircle2 size={12} />
                  : e.action === "Returned"
                    ? <RotateCcw size={12} />
                    : e.action === "Amended"
                      ? <Edit3 size={12} />
                      : e.action === "Accountant Note"
                        ? <ClipboardCheck size={12} />
                        : <Send size={12} />}
              </span>
              <div className="min-w-0 flex-1">
                <div>
                  <span className="font-extrabold">{e.actor}</span> <span className="muted">({e.role})</span> <span>· {e.action}</span>
                  {(e.previousStatus || e.newStatus) && (
                    <span className="muted ml-1">
                      [{e.previousStatus ?? "—"} → {e.newStatus ?? "—"}]
                    </span>
                  )}
                </div>
                {(e.originalAmount != null || e.amendedAmount != null) && (
                  <div className="text-caption muted">
                    {e.originalAmount != null && <>Original: {formatUgxBig(e.originalAmount)}</>}
                    {e.amendedAmount != null && <> · Amended: {formatUgxBig(e.amendedAmount)}</>}
                  </div>
                )}
                {e.reason   && <div className="text-caption muted">Reason: {e.reason}</div>}
                {e.comment  && <div className="text-caption muted italic">&quot;{e.comment}&quot;</div>}
              </div>
              <div className="text-caption muted shrink-0">{e.at}</div>
            </li>
          ))}
        </ul>
      </section>
    </StubPage>
  );
}

function Row({ label, value, bold, tone, pill, strike }: { label: string; value: React.ReactNode; bold?: boolean; tone?: "rose" | "green" | "amber"; pill?: string; strike?: boolean }) {
  const TONE_TEXT = { rose: "text-rose-700", green: "text-emerald-700", amber: "text-amber-700" } as const;
  return (
    <li className="flex items-baseline justify-between gap-2">
      <span className="muted">{label}</span>
      {pill ? (
        <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-caption font-extrabold", pill)}>{value}</span>
      ) : (
        <span className={cn("tabular", bold && "font-extrabold", strike && "line-through opacity-70", tone && TONE_TEXT[tone])}>{value}</span>
      )}
    </li>
  );
}

function Fact({ label, value, bold, span2 }: { label: string; value: React.ReactNode; bold?: boolean; span2?: boolean }) {
  return (
    <div className={cn("rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2.5", span2 && "md:col-span-2")}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight">{label}</div>
      <div className={cn("text-body mt-1 leading-tight", bold && "font-extrabold tabular")}>{value}</div>
    </div>
  );
}

function DecisionImpactPanel({
  impact, sampleReduction, originalBudget,
}: {
  impact: ReturnType<typeof generateDecisionImpactPreview>;
  sampleReduction: number;
  originalBudget:  number;
}) {
  const reductionPct = originalBudget === 0 ? 0 : Math.round((impact.reductionAmount / originalBudget) * 100);
  return (
    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
      <h3 className="text-[12px] font-extrabold tracking-tight uppercase muted mb-2">
        Decision Impact Preview <span className="font-normal normal-case">(example: reduce by {reductionPct}% to {formatUgxBig(sampleReduction)})</span>
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[11.5px]">
        <div>
          <div className="text-caption font-extrabold uppercase tracking-wide text-emerald-700 mb-1">Protected</div>
          {impact.protectedItems.length === 0
            ? <div className="muted">No critical activities flagged.</div>
            : <ul className="space-y-0.5">
                {impact.protectedItems.map((p, i) => (
                  <li key={i}>• {p.count} × {p.label}</li>
                ))}
              </ul>}
        </div>
        <div>
          <div className="text-caption font-extrabold uppercase tracking-wide text-amber-700 mb-1">Deferred</div>
          {impact.deferredItems.length === 0
            ? <div className="muted">No deferrable activities.</div>
            : <ul className="space-y-0.5">
                {impact.deferredItems.map((d, i) => (
                  <li key={i}>• {d.count} × {d.label} <span className="muted">({d.reason})</span></li>
                ))}
              </ul>}
        </div>
        <div>
          <div className="text-caption font-extrabold uppercase tracking-wide text-rose-700 mb-1">Risks</div>
          <ul className="space-y-0.5">
            {impact.risks.map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

const STAGES: { label: string; statuses: ApprovalStatus[] }[] = [
  { label: "Draft / Staff",      statuses: ["Draft", "Submitted to Program Lead", "Returned by Program Lead"] },
  { label: "Program Lead",       statuses: ["Approved by Program Lead", "Submitted to Country Director"] },
  { label: "Country Director",   statuses: ["Returned by Country Director", "Amended by Country Director", "Approved by Country Director", "Submitted to RVP"] },
  { label: "RVP",                statuses: ["Returned by RVP", "Amended by RVP", "Approved by RVP"] },
  { label: "Active",             statuses: ["Final Approved", "Active Funding Plan", "Disbursed", "Closed"] },
];

function StageBar({ status }: { status: ApprovalStatus }) {
  const activeIdx = STAGES.findIndex((stage) => stage.statuses.includes(status));
  return (
    <ol className="flex items-stretch gap-1">
      {STAGES.map((stage, i) => {
        const reached = activeIdx >= 0 && i <= activeIdx;
        const isReturned = stage.statuses.some((st) => st.startsWith("Returned")) && stage.statuses.includes(status);
        return (
          <li key={stage.label} className="flex-1 min-w-0">
            <div className={cn(
              "h-1.5 rounded-full",
              isReturned ? "bg-rose-500" : reached ? "bg-emerald-500" : "bg-[#eef2f4]",
            )} />
            <div className={cn(
              "text-caption mt-1.5 leading-tight font-semibold truncate",
              isReturned ? "text-rose-700" : reached ? "text-emerald-700" : "muted",
            )}>{stage.label}</div>
          </li>
        );
      })}
    </ol>
  );
}
