"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  CornerUpRight,
  Eye,
  MoreHorizontal,
  RefreshCcw,
  Send,
  XCircle,
} from "lucide-react";
import {
  reimbursementQueue,
  type ReimbursementRow,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";

// Tab keys are URL-safe slugs (status strings include spaces, which we
// don't want in `?tab=Supervisor%20Review`). Keep the slug → status map
// next to the tab definitions so the round-trip is obvious.
const TAB_DEFS = [
  { slug: "all",        label: "All",             status: null },
  { slug: "queued",     label: "Queued for me",   status: "Queued for Accountant"  as const },
  { slug: "supervisor", label: "With supervisor", status: "Supervisor Review"      as const },
  { slug: "submitted",  label: "Just submitted",  status: "Submitted"              as const },
  { slug: "returned",   label: "Returned",        status: "Returned for Correction" as const },
] as const;
type TabSlug = (typeof TAB_DEFS)[number]["slug"];
const TAB_SLUGS = TAB_DEFS.map((t) => t.slug) as readonly TabSlug[];

const STATUS_TONE: Record<ReimbursementRow["status"], string> = {
  Submitted:               "bg-amber-100  text-amber-700  border-amber-200",
  "Supervisor Review":     "bg-sky-100    text-sky-700    border-sky-200",
  "Queued for Accountant": "bg-emerald-100 text-emerald-700 border-emerald-200",
  "Returned for Correction": "bg-rose-100 text-rose-700  border-rose-200",
  Reimbursed:              "bg-emerald-100 text-emerald-700 border-emerald-200",
};

const ROUTE_LABEL: Record<ReimbursementRow["approvalRoute"], string> = {
  ProgramLead:      "PL verify",
  CountryDirector:  "CD verify",
  AccountantReview: "Accountant only",
};

const ROLE_LABEL: Record<ReimbursementRow["staffRole"], string> = {
  CCEO:                       "CCEO",
  ProgramLead:                "PL",
  ImpactAssessment:           "IA",
  ProgramAccountant:          "Accountant",
  SpecialProjectsCoordinator: "Special Projects",
  Admin:                      "Admin",
};

// Reimbursement Queue.
//
// Staff submit Personal Funds Claims when they used their own money
// on planned activities. Each claim carries a NetSuite Expense ID and
// an auto-computed "Amount to Reimburse" (spent − previously
// disbursed). Auto-routed: CCEO → PL verify → Accountant. Others →
// CD verify → Accountant.
export function ReimbursementQueue() {
  const [activeSlug, setActiveSlug] = useUrlState<TabSlug>({
    key: "tab",
    defaultValue: "all",
    allowed: TAB_SLUGS,
  });
  const tabs = TAB_DEFS.map((t) => ({
    slug: t.slug,
    label: t.label,
    count: t.status == null
      ? reimbursementQueue.length
      : reimbursementQueue.filter((r) => r.status === t.status).length,
  }));
  const activeStatus = TAB_DEFS.find((t) => t.slug === activeSlug)?.status ?? null;
  const rows = activeStatus == null
    ? reimbursementQueue
    : reimbursementQueue.filter((r) => r.status === activeStatus);

  const totalToReimburse = rows.reduce((a, r) => a + r.amountToReimburseUgx, 0);

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900 inline-flex items-center gap-1.5">
            <CornerUpRight size={14} className="text-emerald-600" />
            Reimbursement Queue
          </h3>
          <p className="text-caption muted font-semibold mt-0.5">
            Personal Funds Claims · NetSuite Expense ID confirmed
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap text-right">
          <div className="px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200">
            <div className="text-[9.5px] muted font-extrabold uppercase tracking-[0.1em]">
              To Reimburse
            </div>
            <div className="text-[13px] font-extrabold tabular num-hero text-emerald-700 leading-none mt-0.5">
              UGX {(totalToReimburse / 1_000_000).toFixed(2)}M
            </div>
          </div>
        </div>
      </header>

      <nav className="flex items-center gap-1.5 mb-3 overflow-x-auto pb-1 -mx-1 px-1">
        {tabs.map((t) => {
          const isActive = t.slug === activeSlug;
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => setActiveSlug(t.slug)}
              aria-pressed={isActive}
              className={cn(
                "h-8 px-3 rounded-lg text-[11.5px] font-extrabold whitespace-nowrap inline-flex items-center gap-1.5 transition-all duration-200",
                isActive
                  ? "bg-slate-900 text-white shadow-[0_8px_18px_-8px_rgba(15,23,32,0.4)]"
                  : "bg-white text-slate-600 border border-[var(--color-edify-border)] hover:bg-slate-50 hover:border-slate-300",
              )}
            >
              {t.label}
              <span
                className={cn(
                  "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                  isActive ? "bg-white/15 text-white" : "bg-slate-100 text-slate-700",
                )}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </nav>

      <ul className="flex flex-col gap-2 flex-1">
        {rows.length === 0 && (
          <li className="text-[12px] muted italic py-8 text-center">
            No reimbursement claims match this filter.
          </li>
        )}
        {rows.map((r, i) => {
          const canReimburse = r.status === "Queued for Accountant";
          const canApprove = r.status === "Submitted" || r.status === "Supervisor Review";
          return (
            <li
              key={r.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex flex-col gap-2 card-lift tile-in min-w-0",
                `stagger-${(i % 6) + 1}`,
              )}
            >
              <div className="flex items-start gap-2.5 flex-wrap">
                <span className="w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-[0_4px_10px_-4px_rgba(16,185,129,0.45)]">
                  {r.initials}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-body font-extrabold text-slate-900 truncate">
                      {r.staff}
                    </span>
                    <span className="text-[10px] muted font-semibold">({ROLE_LABEL[r.staffRole]})</span>
                    <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-slate-100 text-slate-700">
                      {ROUTE_LABEL[r.approvalRoute]}
                    </span>
                    {r.autoCreated && (
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-sky-100 text-sky-700 border border-sky-200"
                        title="Auto-created from reconciliation overspend"
                      >
                        <Bot size={9} />
                        Auto from reconciliation
                      </span>
                    )}
                    {r.thresholdFlag === "RequiresCDReview" && (
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-rose-100 text-rose-700 border border-rose-200"
                        title={`Overspend ${r.overspendPct?.toFixed(1) ?? ""}% — routed to Country Director`}
                      >
                        <AlertTriangle size={9} />
                        High overspend · CD review
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-700 font-semibold truncate mt-0.5">
                    {r.activity}
                  </div>
                  <div className="text-[10px] muted font-semibold truncate tabular">
                    {r.weekRange} · {r.id} · submitted {r.submittedAt}
                    {r.fundReconciliationId && (
                      <> · <span className="text-sky-700 font-extrabold">{r.fundReconciliationId}</span></>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular num-hero text-slate-900 leading-none glow-emerald">
                    UGX {(r.amountToReimburseUgx / 1_000_000).toFixed(2)}M
                  </div>
                  <div className="text-[9.5px] muted font-semibold mt-1">
                    to reimburse
                  </div>
                </div>
              </div>

              {/* Cost decomposition */}
              <div className="grid grid-cols-3 gap-1.5">
                <CostChip label="Amount spent"            value={r.amountSpentUgx} tone="slate" />
                <CostChip label="Previously disbursed"    value={r.amountDisbursedUgx} tone="sky" />
                <CostChip label="Reimbursement due"       value={r.amountToReimburseUgx} tone="emerald" />
              </div>

              {/* NetSuite ID + reason */}
              <div className="grid grid-cols-1 sm:grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-caption">
                <span className="muted font-extrabold uppercase tracking-[0.08em]">NetSuite ID</span>
                <span className="font-extrabold text-sky-700 tabular">{r.netsuiteExpenseId}</span>
                <span className="muted font-extrabold uppercase tracking-[0.08em]">Reason</span>
                <span className="font-semibold text-slate-700 truncate">{r.reason}</span>
              </div>

              {/* Action row */}
              <div className="flex items-center justify-between gap-2 flex-wrap pt-1.5 border-t border-dashed border-[var(--color-edify-divider)]">
                <span
                  className={cn(
                    "inline-flex items-center px-2 py-[3px] rounded-full text-[10px] font-extrabold border whitespace-nowrap",
                    STATUS_TONE[r.status],
                  )}
                >
                  {r.status}
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-caption font-extrabold text-slate-700"
                  >
                    <Eye size={11} />
                    Review
                  </button>
                  {canApprove && (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-white border border-rose-200 hover:bg-rose-50 text-caption font-extrabold text-rose-700"
                    >
                      <XCircle size={11} />
                      Return
                    </button>
                  )}
                  {r.status === "Returned for Correction" ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-caption font-extrabold shadow-[0_6px_14px_-6px_rgba(15,23,32,0.5)]"
                    >
                      <RefreshCcw size={11} />
                      Resubmit
                    </button>
                  ) : canReimburse ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-caption font-extrabold shadow-[0_6px_14px_-6px_rgba(16,185,129,0.55)]"
                    >
                      <Send size={11} />
                      Mark Reimbursed
                    </button>
                  ) : canApprove ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-caption font-extrabold shadow-[0_6px_14px_-6px_rgba(15,23,32,0.5)]"
                    >
                      <CheckCircle2 size={11} />
                      Approve
                    </button>
                  ) : null}
                  <button
                    type="button"
                    aria-label="More"
                    className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-slate-500"
                  >
                    <MoreHorizontal size={12} />
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <a
        href="#reimbursements-all"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All reimbursement claims
        <ArrowUpRight size={11} />
      </a>
    </article>
  );
}

const COST_TONE: Record<string, string> = {
  slate:   "bg-slate-50    text-slate-700",
  sky:     "bg-sky-50      text-sky-700",
  emerald: "bg-emerald-50  text-emerald-700",
};

function CostChip({
  label, value, tone,
}: { label: string; value: number; tone: keyof typeof COST_TONE }) {
  return (
    <div className={cn("rounded-lg px-2 py-1.5", COST_TONE[tone])}>
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.08em] opacity-80">
        {label}
      </div>
      <div className="text-[12px] font-extrabold tabular num-hero leading-none mt-0.5">
        UGX {(value / 1_000_000).toFixed(2)}M
      </div>
    </div>
  );
}
