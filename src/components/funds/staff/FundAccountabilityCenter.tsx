"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Banknote,
  CheckCircle2,
  CornerUpRight,
  ExternalLink,
  FileText,
  Lock,
  Send,
  Sparkles,
} from "lucide-react";
import {
  computeOverspendThreshold,
  formatMoney,
  OVERSPEND_HIGH_THRESHOLD_PCT,
} from "@/lib/funds/weekly-fund-engine";
import { isValidId, ID_FORMATS } from "@/lib/intake/id-formats";
import { cn } from "@/lib/utils";
import {
  OVERSPEND_REASON_LABEL,
  type Money,
  type OverspendReason,
  type WeeklyFundRequest,
  type WeeklyFundRequestStatus,
} from "@/lib/funds/weekly-fund-types";

// Fund Accountability Center (staff-facing).
//
// Renders the post-disbursement experience for a single weekly fund
// request. The section is *locked* until the staff member confirms
// receipt — that's the gate the spec calls out:
//
//   APPROVED                 → "Awaiting accountant disbursement"
//   DISBURSED                → "Funds disbursed. Please confirm receipt." + Confirm CTA
//   RECEIVED / IN_USE        → unlocked Accountability Center (enter NetSuite ID)
//   ACCOUNTABILITY_SUBMITTED → pending accountant review
//   ACCOUNTABILITY_RETURNED  → returned for correction with reason
//   ACCOUNTABILITY_APPROVED  → closed
//
// The card always shows a status preview so the staff knows what's
// coming next; the form fields only enable once the gate flips.
export function FundAccountabilityCenter({
  request,
  onConfirmReceipt,
  onSubmitAccountability,
  onOpenReimbursement,
}: {
  request: WeeklyFundRequest;
  onConfirmReceipt?: () => void;
  onSubmitAccountability?: (payload: AccountabilityFormPayload) => void;
  onOpenReimbursement?: () => void;
}) {
  const phase = phaseOf(request.status);
  const isLocked = phase === "locked";
  const isAwaitingReceipt = phase === "awaiting-receipt";
  const isOpen = phase === "open";
  const isPending = phase === "pending-review";
  const isReturned = phase === "returned";
  const isClosed = phase === "closed";

  return (
    <article className="card p-5 lg:p-6 flex flex-col gap-4">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900 inline-flex items-center gap-1.5">
            <Sparkles size={14} className="text-emerald-600" />
            Fund Accountability Center
          </h2>
          <p className="text-[11px] muted font-semibold mt-0.5">
            Week {request.period.weekOfMonth} · {request.period.weekStartIso} → {request.period.weekEndIso}
          </p>
        </div>
        <PhaseChip phase={phase} />
      </header>

      {/* Money trail */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <MoneyTile label="Disbursed"  value={request.disbursedAmount ? formatMoney(request.disbursedAmount) : "—"} tone="emerald" />
        <MoneyTile label="Received"   value={isLocked || isAwaitingReceipt ? "—" : formatMoney(request.disbursedAmount ?? { amount: 0, currency: "UGX" })} tone="sky" />
        <MoneyTile label="NetSuite Status" value={isClosed ? "Confirmed" : isPending ? "Submitted" : isOpen ? "Pending" : isReturned ? "Returned" : "—"} tone="slate" textual />
        <MoneyTile label="Accountability" value={isClosed ? "Closed" : isPending ? "Pending review" : isReturned ? "Returned" : isOpen ? "Open" : "Not Open"} tone="slate" textual />
      </div>

      {/* Locked preview */}
      {isLocked && (
        <LockedNote
          message="Fund request approved. Awaiting accountant disbursement."
          sublabel="The Accountability Center will unlock once you confirm receipt of disbursed funds."
        />
      )}

      {/* Awaiting receipt — staff must click Confirm Received */}
      {isAwaitingReceipt && (
        <ReceiptCallToAction
          amount={request.disbursedAmount}
          onConfirmReceipt={onConfirmReceipt}
        />
      )}

      {/* Open: NetSuite ID submission form */}
      {(isOpen || isReturned) && (
        <AccountabilityForm
          request={request}
          isReturned={isReturned}
          onSubmit={(payload) => onSubmitAccountability?.(payload)}
          onOpenReimbursement={onOpenReimbursement}
        />
      )}

      {/* Pending accountant review */}
      {isPending && (
        <div className="rounded-xl border border-sky-100 bg-sky-50/40 p-3.5 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl grid place-items-center shrink-0 bg-sky-100">
            <FileText size={14} className="text-sky-600" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-extrabold text-slate-900">
              Accountability Submitted
            </div>
            <div className="text-[11px] muted font-semibold mt-0.5">
              Awaiting accountant review. You&apos;ll be notified when it&apos;s approved or returned.
            </div>
          </div>
        </div>
      )}

      {/* Closed / approved */}
      {isClosed && (
        <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3.5 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl grid place-items-center shrink-0 bg-emerald-100">
            <CheckCircle2 size={14} className="text-emerald-600" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-extrabold text-slate-900">
              Accountability Approved
            </div>
            <div className="text-[11px] muted font-semibold mt-0.5">
              This Week is closed. Future fund releases are unlocked for you.
            </div>
          </div>
        </div>
      )}

      {/* Reimbursement nudge — always available except in locked state */}
      {!isLocked && (
        <button
          type="button"
          onClick={() => onOpenReimbursement?.()}
          className="rounded-xl border border-violet-100 bg-violet-50/40 hover:bg-violet-50 p-3.5 flex items-start gap-3 text-left transition-colors group"
        >
          <span className="w-9 h-9 rounded-xl grid place-items-center shrink-0 bg-violet-100 group-hover:bg-violet-200 transition-colors">
            <CornerUpRight size={14} className="text-violet-600" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-extrabold text-slate-900 inline-flex items-center gap-1.5">
              Used your own money on a planned activity?
              <ArrowUpRight size={11} className="text-violet-600" />
            </div>
            <div className="text-[11px] muted font-semibold mt-0.5">
              Submit a Personal Funds Claim with your NetSuite Expense ID — we&apos;ll calculate the reimbursement automatically.
            </div>
          </div>
        </button>
      )}
    </article>
  );
}

// ────────── Sub-components ────────────────────────────────────────────

type Phase =
  | "locked"
  | "awaiting-receipt"
  | "open"
  | "pending-review"
  | "returned"
  | "closed";

function phaseOf(s: WeeklyFundRequestStatus): Phase {
  if (s === "DISBURSED") return "awaiting-receipt";
  if (s === "RECEIVED" || s === "IN_USE") return "open";
  if (s === "ACCOUNTABILITY_SUBMITTED") return "pending-review";
  if (s === "ACCOUNTABILITY_RETURNED") return "returned";
  if (s === "ACCOUNTABILITY_APPROVED" || s === "CLOSED" || s === "ARCHIVED") return "closed";
  return "locked";
}

const PHASE_CHIP: Record<
  Phase,
  { label: string; chip: string; Icon: typeof CheckCircle2 }
> = {
  locked:            { label: "Awaiting Disbursement", chip: "bg-slate-100 text-slate-700 border-slate-200",      Icon: Lock },
  "awaiting-receipt":{ label: "Confirm Receipt",       chip: "bg-amber-100 text-amber-700 border-amber-200",      Icon: Banknote },
  open:              { label: "Accountability Open",   chip: "bg-emerald-100 text-emerald-700 border-emerald-200", Icon: Sparkles },
  "pending-review":  { label: "Pending Review",        chip: "bg-sky-100 text-sky-700 border-sky-200",            Icon: FileText },
  returned:          { label: "Returned for Correction", chip: "bg-rose-100 text-rose-700 border-rose-200",       Icon: AlertTriangle },
  closed:            { label: "Closed",                chip: "bg-emerald-100 text-emerald-700 border-emerald-200", Icon: CheckCircle2 },
};

function PhaseChip({ phase }: { phase: Phase }) {
  const c = PHASE_CHIP[phase];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-[10px] font-extrabold border whitespace-nowrap",
        c.chip,
      )}
    >
      <c.Icon size={11} />
      {c.label}
    </span>
  );
}

const TILE_TONE: Record<string, { bg: string; fg: string }> = {
  emerald: { bg: "bg-emerald-50", fg: "text-emerald-700" },
  sky:     { bg: "bg-sky-50",     fg: "text-sky-700" },
  slate:   { bg: "bg-slate-50",   fg: "text-slate-700" },
};

function MoneyTile({
  label, value, tone, textual,
}: {
  label: string;
  value: string;
  tone: keyof typeof TILE_TONE;
  textual?: boolean;
}) {
  const t = TILE_TONE[tone];
  return (
    <div className={cn("rounded-xl border border-[var(--color-edify-border)] p-2.5", t.bg)}>
      <div className="text-[9.5px] muted font-extrabold uppercase tracking-[0.08em]">
        {label}
      </div>
      <div
        className={cn(
          "font-extrabold tabular num-hero leading-none mt-1",
          textual ? "text-[12px]" : "text-[13.5px]",
          t.fg,
        )}
      >
        {value}
      </div>
    </div>
  );
}

function LockedNote({ message, sublabel }: { message: string; sublabel: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 flex items-start gap-3">
      <span className="w-9 h-9 rounded-xl grid place-items-center shrink-0 bg-slate-100">
        <Lock size={14} className="text-slate-500" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-extrabold text-slate-700">{message}</div>
        <div className="text-[11px] muted font-semibold mt-0.5">{sublabel}</div>
      </div>
    </div>
  );
}

function ReceiptCallToAction({
  amount,
  onConfirmReceipt,
}: {
  amount?: Money;
  onConfirmReceipt?: () => void;
}) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 flex items-start gap-3 flex-wrap">
      <span className="w-10 h-10 rounded-xl grid place-items-center shrink-0 bg-amber-100">
        <Banknote size={15} className="text-amber-600" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-extrabold text-slate-900">
          Funds Disbursed
        </div>
        <div className="text-[11.5px] text-slate-700 mt-0.5">
          {amount ? formatMoney(amount) : "Funds"} has been disbursed to you. Please check your account
          and confirm receipt. The Accountability Center will unlock immediately.
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap ml-auto">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
        >
          Report Issue
        </button>
        <button
          type="button"
          onClick={() => onConfirmReceipt?.()}
          className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[12px] font-extrabold shadow-[0_8px_22px_-8px_rgba(16,185,129,0.5)]"
        >
          <CheckCircle2 size={12} />
          Confirm Received
        </button>
      </div>
    </div>
  );
}

export type AccountabilityFormPayload = {
  netsuiteExpenseId: string;
  amountSpentUgx: number;
  accountabilityNote?: string;
  overspendReason?: OverspendReason;
  overspendNote?: string;
  outcome: "Fully Accounted" | "Balance To Return" | "Reimbursement Due";
};

function AccountabilityForm({
  request,
  isReturned,
  onSubmit,
}: {
  request: WeeklyFundRequest;
  isReturned: boolean;
  onSubmit: (payload: AccountabilityFormPayload) => void;
  onOpenReimbursement?: () => void;
}) {
  const disbursedAmount = request.disbursedAmount?.amount ?? 0;
  const [netsuiteId, setNetsuiteId] = useState("");
  const [amountSpent, setAmountSpent] = useState(disbursedAmount);
  const [note, setNote] = useState("");
  const [overspendReason, setOverspendReason] = useState<OverspendReason | "">("");
  const [overspendNote, setOverspendNote] = useState("");

  const idOk = isValidId("expense", netsuiteId);
  const diff = amountSpent - disbursedAmount;
  const fullyAccounted = diff === 0;
  const isUnderspend = diff < 0;
  const isOverspend = diff > 0;
  const balance = isUnderspend ? -diff : 0;
  const reimbursementDue = isOverspend ? diff : 0;
  const { pct, flag } = computeOverspendThreshold(disbursedAmount, amountSpent);
  const requiresCdReview = flag === "RequiresCDReview";
  const outcome: AccountabilityFormPayload["outcome"] = fullyAccounted
    ? "Fully Accounted"
    : isUnderspend
      ? "Balance To Return"
      : "Reimbursement Due";

  const canSubmit =
    idOk
    && amountSpent > 0
    && (!isOverspend || (!!overspendReason && (overspendReason !== "Other" || overspendNote.trim().length >= 5)));

  const submitLabel = isOverspend
    ? "Submit Accountability & Reimbursement Request"
    : isUnderspend
      ? "Submit Accountability & Balance Return"
      : "Submit Accountability";

  return (
    <div className="rounded-xl border border-emerald-100 bg-emerald-50/30 p-4 flex flex-col gap-3">
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <div className="min-w-0">
          <div className="text-body font-extrabold text-slate-900">
            Accountability Enabled
          </div>
          <div className="text-[11px] muted font-semibold">
            Reconcile your NetSuite spend against the advanced amount — Edify auto-creates the next step.
          </div>
        </div>
        <a
          href="#netsuite"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-sky-700 hover:text-sky-800"
        >
          Open NetSuite
          <ExternalLink size={10} />
        </a>
      </header>

      {isReturned && request.notes && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-700 font-semibold">
          <span className="font-extrabold">Accountant returned this:</span>{" "}
          {request.notes}
        </div>
      )}

      {/* NetSuite ID */}
      <div>
        <label className="block text-caption font-extrabold text-slate-700 mb-1 uppercase tracking-[0.08em]">
          NetSuite Expense ID <span className="text-rose-600">*</span>
        </label>
        <input
          type="text"
          value={netsuiteId}
          onChange={(e) => setNetsuiteId(e.target.value)}
          placeholder={`e.g. ${ID_FORMATS.expense.example}`}
          className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500/25 focus:border-emerald-300"
        />
        {netsuiteId.length > 0 && !idOk && (
          <div className="text-[10px] text-rose-600 font-semibold mt-1">
            Expense ID must be {ID_FORMATS.expense.hint}
          </div>
        )}
      </div>

      {/* Amount spent */}
      <div>
        <label className="block text-caption font-extrabold text-slate-700 mb-1 uppercase tracking-[0.08em]">
          Reconciled amount spent (UGX) <span className="text-rose-600">*</span>
        </label>
        <input
          type="number"
          min={0}
          value={amountSpent}
          onChange={(e) => setAmountSpent(Number(e.target.value))}
          className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500/25 focus:border-emerald-300"
        />
        <div className="text-[10px] muted font-semibold mt-1">
          Pull this number from your posted expense in NetSuite.
        </div>
      </div>

      {/* Reconciliation Summary — the brain of this card */}
      <ReconciliationSummary
        disbursedAmount={disbursedAmount}
        amountSpent={amountSpent}
        balance={balance}
        reimbursementDue={reimbursementDue}
        outcome={outcome}
        overspendPct={pct}
        requiresCdReview={requiresCdReview}
      />

      {/* Overspend reason picker — required when isOverspend */}
      {isOverspend && (
        <div className="rounded-lg border border-violet-200 bg-white p-3 flex flex-col gap-2">
          <label className="block text-caption font-extrabold text-slate-700 uppercase tracking-[0.08em]">
            Why did you spend more than the advance? <span className="text-rose-600">*</span>
          </label>
          <select
            value={overspendReason}
            onChange={(e) => setOverspendReason(e.target.value as OverspendReason)}
            className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300"
          >
            <option value="">Pick a reason…</option>
            {(Object.keys(OVERSPEND_REASON_LABEL) as OverspendReason[]).map((k) => (
              <option key={k} value={k}>{OVERSPEND_REASON_LABEL[k]}</option>
            ))}
          </select>
          {(overspendReason === "Other" || overspendReason) && (
            <textarea
              value={overspendNote}
              onChange={(e) => setOverspendNote(e.target.value)}
              rows={2}
              placeholder={
                overspendReason === "Other"
                  ? "Explain briefly (required for 'Other')"
                  : "Optional context for your supervisor (e.g. specific route, school name)"
              }
              className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300 resize-y"
            />
          )}
          {requiresCdReview && (
            <div className="rounded-md bg-rose-50 border border-rose-200 px-2.5 py-1.5 text-caption font-extrabold text-rose-700 inline-flex items-center gap-1">
              <AlertTriangle size={11} />
              Overspend &gt; {OVERSPEND_HIGH_THRESHOLD_PCT}% — claim will route to the Country Director.
            </div>
          )}
        </div>
      )}

      {/* Accountability note */}
      <div>
        <label className="block text-caption font-extrabold text-slate-700 mb-1 uppercase tracking-[0.08em]">
          Short accountability note
        </label>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="Optional context — receipts attached in NetSuite already…"
          className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] text-slate-700 outline-none focus:ring-2 focus:ring-emerald-500/25 focus:border-emerald-300 resize-y"
        />
      </div>

      {/* Submit */}
      <footer className="flex items-center justify-between gap-2 flex-wrap pt-1">
        <span className="text-caption muted font-semibold">
          {isOverspend
            ? "Edify will auto-create the reimbursement claim — no separate form needed."
            : isUnderspend
              ? "Edify will auto-create a balance-return record. Confirm the return method afterwards."
              : "Accountability cannot close without a valid NetSuite Expense ID."}
        </span>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() =>
            onSubmit({
              netsuiteExpenseId: netsuiteId.trim(),
              amountSpentUgx: amountSpent,
              accountabilityNote: note.trim() || undefined,
              overspendReason: isOverspend ? (overspendReason as OverspendReason) : undefined,
              overspendNote: isOverspend ? (overspendNote.trim() || undefined) : undefined,
              outcome,
            })
          }
          className={cn(
            "inline-flex items-center gap-1.5 h-10 px-4 rounded-lg text-body font-extrabold transition-colors",
            canSubmit
              ? "bg-slate-900 hover:bg-slate-800 text-white shadow-[0_10px_28px_-12px_rgba(15,23,32,0.55)]"
              : "bg-slate-100 text-slate-400 cursor-not-allowed",
          )}
        >
          <Send size={13} />
          {submitLabel}
        </button>
      </footer>
    </div>
  );
}

// Reconciliation summary — premium 3-state card that updates live as
// the staff edits the amount-spent field. Communicates the system's
// decision *before* submit.
function ReconciliationSummary({
  disbursedAmount,
  amountSpent,
  balance,
  reimbursementDue,
  outcome,
  overspendPct,
  requiresCdReview,
}: {
  disbursedAmount: number;
  amountSpent: number;
  balance: number;
  reimbursementDue: number;
  outcome: "Fully Accounted" | "Balance To Return" | "Reimbursement Due";
  overspendPct: number;
  requiresCdReview: boolean;
}) {
  const palette =
    outcome === "Fully Accounted"
      ? { ring: "ring-emerald-200", bg: "bg-emerald-50", fg: "text-emerald-700", chipBg: "bg-emerald-100", icon: <CheckCircle2 size={13} /> }
      : outcome === "Balance To Return"
        ? { ring: "ring-amber-200", bg: "bg-amber-50/60", fg: "text-amber-700", chipBg: "bg-amber-100", icon: <CornerUpRight size={13} /> }
        : { ring: "ring-violet-200", bg: "bg-violet-50/60", fg: "text-violet-700", chipBg: "bg-violet-100", icon: <CornerUpRight size={13} /> };

  return (
    <div className={cn("rounded-xl ring-2 p-3.5 flex flex-col gap-2.5", palette.ring, palette.bg)}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-caption font-extrabold uppercase tracking-[0.1em] text-slate-700">
          Reconciliation Summary
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-[10px] font-extrabold whitespace-nowrap",
            palette.chipBg,
            palette.fg,
          )}
        >
          {palette.icon}
          {outcome}
        </span>
      </div>

      {/* Live stat grid */}
      <div className="grid grid-cols-3 gap-2">
        <SummaryCell label="Advanced to you"     value={`UGX ${disbursedAmount.toLocaleString()}`} tone="slate" />
        <SummaryCell label="Reconciled in NetSuite" value={`UGX ${amountSpent.toLocaleString()}`}    tone="sky" />
        {outcome === "Fully Accounted" && (
          <SummaryCell label="Difference" value="UGX 0" tone="emerald" />
        )}
        {outcome === "Balance To Return" && (
          <SummaryCell label="Balance to return" value={`UGX ${balance.toLocaleString()}`} tone="amber" />
        )}
        {outcome === "Reimbursement Due" && (
          <SummaryCell label="Reimbursement due" value={`UGX ${reimbursementDue.toLocaleString()}`} tone="violet" />
        )}
      </div>

      {/* Outcome message */}
      <p className={cn("text-[11px] font-semibold leading-snug", palette.fg)}>
        {outcome === "Fully Accounted" && (
          <>The advance and the spend match. Accountability will go straight to accountant review.</>
        )}
        {outcome === "Balance To Return" && (
          <>You spent <b className="tabular">UGX {amountSpent.toLocaleString()}</b> of the <b className="tabular">UGX {disbursedAmount.toLocaleString()}</b> advanced. Edify will create a Balance Return record for <b className="tabular">UGX {balance.toLocaleString()}</b>. Accountability closes once you confirm the return method.</>
        )}
        {outcome === "Reimbursement Due" && (
          <>You spent <b className="tabular">UGX {amountSpent.toLocaleString()}</b> against an advance of <b className="tabular">UGX {disbursedAmount.toLocaleString()}</b> ({overspendPct.toFixed(1)}% over). Edify will automatically create a reimbursement request for <b className="tabular">UGX {reimbursementDue.toLocaleString()}</b>, sent to {requiresCdReview ? "the Country Director" : "your Program Lead"} for review.</>
        )}
      </p>
    </div>
  );
}

function SummaryCell({
  label, value, tone,
}: {
  label: string;
  value: string;
  tone: "slate" | "sky" | "emerald" | "amber" | "violet";
}) {
  const palette: Record<string, { bg: string; fg: string }> = {
    slate:   { bg: "bg-white",        fg: "text-slate-900" },
    sky:     { bg: "bg-white",        fg: "text-sky-700" },
    emerald: { bg: "bg-emerald-100",  fg: "text-emerald-700" },
    amber:   { bg: "bg-amber-100",    fg: "text-amber-700" },
    violet:  { bg: "bg-violet-100",   fg: "text-violet-700" },
  };
  const t = palette[tone];
  return (
    <div className={cn("rounded-lg px-2.5 py-2 border border-white/40", t.bg)}>
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.08em] muted leading-tight">
        {label}
      </div>
      <div className={cn("text-[13.5px] font-extrabold tabular num-hero leading-none mt-1", t.fg)}>
        {value}
      </div>
    </div>
  );
}

