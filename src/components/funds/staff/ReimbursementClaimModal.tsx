"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CornerUpRight,
  ExternalLink,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { isValidId, ID_FORMATS } from "@/lib/intake/id-formats";

// Reimbursement Claim modal (Personal Funds Claim).
//
// Two paths matching the spec:
//   A. I was disbursed funds but spent more — reimburse the difference
//   B. I used my own money first — reimburse the full amount
//
// Required fields per path:
//   • Activity covered          (links to plan)
//   • Date spent
//   • Amount spent
//   • Amount previously disbursed (auto-filled when known)
//   • Reason personal funds were used
//   • NetSuite Expense ID       (validated digits-only, e.g. 6161)
//   • Supporting note
//
// Auto-computed: Amount to Reimburse = Spent − Previously Disbursed.
// Submitting routes to PL (for CCEO) or CD (for everyone else).
export function ReimbursementClaimModal({
  open,
  onClose,
  onSubmit,
  defaults,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit?: (payload: ReimbursementClaimPayload) => void;
  defaults?: {
    activityTitle?: string;
    weeklyPlanId?: string;
    fundRequestId?: string;
    amountPreviouslyDisbursedUgx?: number;
  };
}) {
  if (!open) return null;
  return (
    <Inner
      onClose={onClose}
      onSubmit={onSubmit}
      defaults={defaults}
    />
  );
}

export type ReimbursementClaimPayload = {
  path: "topUp" | "personalFirst";
  activityTitle: string;
  dateSpent: string;
  amountSpentUgx: number;
  amountPreviouslyDisbursedUgx: number;
  amountToReimburseUgx: number;
  reasonPersonalFundsUsed: string;
  netsuiteExpenseId: string;
  note?: string;
};

function Inner({
  onClose,
  onSubmit,
  defaults,
}: {
  onClose: () => void;
  onSubmit?: (payload: ReimbursementClaimPayload) => void;
  defaults?: {
    activityTitle?: string;
    weeklyPlanId?: string;
    fundRequestId?: string;
    amountPreviouslyDisbursedUgx?: number;
  };
}) {
  const [path, setPath] = useState<"topUp" | "personalFirst">(
    defaults?.amountPreviouslyDisbursedUgx && defaults.amountPreviouslyDisbursedUgx > 0
      ? "topUp"
      : "personalFirst",
  );
  const [activityTitle, setActivityTitle] = useState(defaults?.activityTitle ?? "");
  const [dateSpent, setDateSpent] = useState(() => new Date().toISOString().slice(0, 10));
  const [amountSpent, setAmountSpent] = useState<number>(0);
  const [amountPreviouslyDisbursed, setAmountPreviouslyDisbursed] = useState<number>(
    defaults?.amountPreviouslyDisbursedUgx ?? 0,
  );
  const [reason, setReason] = useState("");
  const [netsuiteId, setNetsuiteId] = useState("");
  const [note, setNote] = useState("");

  const idOk = isValidId("expense", netsuiteId);
  const previously = path === "personalFirst" ? 0 : amountPreviouslyDisbursed;
  const toReimburse = Math.max(amountSpent - previously, 0);
  const overReason = reason.trim().length >= 5;
  const activityOk = activityTitle.trim().length >= 3;
  const amountOk = amountSpent > 0;
  const canSubmit = idOk && activityOk && amountOk && overReason && toReimburse > 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center px-3"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/45 backdrop-blur-sm"
      />
      <article className="card relative w-full max-w-xl p-5 max-h-[92vh] overflow-y-auto">
        <header className="flex items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            <h2 className="text-[16px] font-extrabold tracking-tight text-slate-900 inline-flex items-center gap-1.5">
              <CornerUpRight size={15} className="text-violet-600" />
              Personal Funds Claim
            </h2>
            <p className="text-[11.5px] muted font-semibold mt-1 leading-tight">
              Submit a reimbursement claim for activities where you used your own money.
              Your claim routes to your supervisor for verification, then to the
              accountant for payment.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 grid place-items-center rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-600"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </header>

        {/* Path picker */}
        <section className="mb-4">
          <Label>Which path applies?</Label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <PathBtn
              active={path === "topUp"}
              onClick={() => setPath("topUp")}
              title="I was disbursed, but spent more"
              sub="Top-up reimbursement for an extra spend on the same activity."
            />
            <PathBtn
              active={path === "personalFirst"}
              onClick={() => setPath("personalFirst")}
              title="I used my own money first"
              sub="No prior disbursement on this activity — reimburse the full amount."
            />
          </div>
        </section>

        {/* Activity */}
        <section className="mb-3">
          <Label>Activity covered *</Label>
          <input
            type="text"
            value={activityTitle}
            onChange={(e) => setActivityTitle(e.target.value)}
            placeholder="e.g. Week 2 school visits · St Mary's Naguru"
            className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300"
          />
        </section>

        {/* Date */}
        <section className="mb-3">
          <Label>Date spent</Label>
          <input
            type="date"
            value={dateSpent}
            onChange={(e) => setDateSpent(e.target.value)}
            className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300"
          />
        </section>

        {/* Amounts */}
        <section className="mb-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <Label>Amount spent (UGX) *</Label>
            <input
              type="number"
              min={0}
              value={amountSpent}
              onChange={(e) => setAmountSpent(Number(e.target.value))}
              className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300"
            />
          </div>
          <div>
            <Label>Previously disbursed (UGX)</Label>
            <input
              type="number"
              min={0}
              disabled={path === "personalFirst"}
              value={path === "personalFirst" ? 0 : amountPreviouslyDisbursed}
              onChange={(e) => setAmountPreviouslyDisbursed(Number(e.target.value))}
              className={cn(
                "w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-body font-extrabold tabular outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300",
                path === "personalFirst"
                  ? "bg-slate-50 text-slate-400 cursor-not-allowed"
                  : "bg-white text-slate-900",
              )}
            />
          </div>
        </section>

        {/* Auto-calc */}
        <section className="mb-3 rounded-xl border border-violet-200 bg-violet-50/40 p-3.5">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="text-caption font-extrabold uppercase tracking-[0.1em] text-violet-700">
              Amount to Reimburse
            </div>
            <div className="text-[18px] font-extrabold tabular num-hero text-violet-700 leading-none glow-emerald">
              UGX {toReimburse.toLocaleString()}
            </div>
          </div>
          <div className="text-caption muted font-semibold mt-1">
            Spent {amountSpent.toLocaleString()} − previously disbursed {previously.toLocaleString()}
          </div>
        </section>

        {/* Reason */}
        <section className="mb-3">
          <Label>Why did you use personal funds? *</Label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="e.g. Flood detour required boda; venue demanded same-day deposit; etc."
            className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300 resize-y"
          />
          {reason.length > 0 && !overReason && (
            <Hint tone="rose">Reason must be at least 5 characters.</Hint>
          )}
        </section>

        {/* NetSuite */}
        <section className="mb-3">
          <Label>NetSuite Expense ID *</Label>
          <input
            type="text"
            value={netsuiteId}
            onChange={(e) => setNetsuiteId(e.target.value)}
            placeholder={`e.g. ${ID_FORMATS.expense.example}`}
            className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300"
          />
          <div className="flex items-center justify-between gap-2 mt-1">
            <Hint tone="amber">
              Post the expense in NetSuite first, then paste the ID here.
            </Hint>
            <a
              href="#netsuite"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-caption font-extrabold text-sky-700"
            >
              Open NetSuite
              <ExternalLink size={10} />
            </a>
          </div>
          {netsuiteId.length > 0 && !idOk && (
            <Hint tone="rose">Expense ID must be {ID_FORMATS.expense.hint}</Hint>
          )}
        </section>

        {/* Note */}
        <section className="mb-4">
          <Label>Supporting note</Label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Optional — receipts already attached in NetSuite, etc."
            className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] text-slate-700 outline-none focus:ring-2 focus:ring-violet-500/25 focus:border-violet-300 resize-y"
          />
        </section>

        {/* Submit */}
        <footer className="flex items-center justify-between gap-2 flex-wrap pt-1">
          <span className="text-caption muted font-semibold inline-flex items-center gap-1">
            <CheckCircle2 size={11} className="text-emerald-600" />
            Auto-routed to your supervisor, then to the accountant.
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() =>
                onSubmit?.({
                  path,
                  activityTitle: activityTitle.trim(),
                  dateSpent,
                  amountSpentUgx: amountSpent,
                  amountPreviouslyDisbursedUgx: previously,
                  amountToReimburseUgx: toReimburse,
                  reasonPersonalFundsUsed: reason.trim(),
                  netsuiteExpenseId: netsuiteId.trim(),
                  note: note.trim() || undefined,
                })
              }
              className={cn(
                "inline-flex items-center gap-1.5 h-10 px-4 rounded-lg text-body font-extrabold transition-colors",
                canSubmit
                  ? "bg-violet-600 hover:bg-violet-700 text-white shadow-[0_10px_28px_-12px_rgba(139,92,246,0.55)]"
                  : "bg-slate-100 text-slate-400 cursor-not-allowed",
              )}
            >
              <CornerUpRight size={13} />
              Submit Reimbursement Claim
            </button>
          </div>
        </footer>
      </article>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-caption font-extrabold text-slate-700 mb-1 uppercase tracking-[0.08em]">
      {children}
    </label>
  );
}

function Hint({
  tone, children,
}: { tone: "rose" | "amber"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "mt-1.5 inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-semibold",
        tone === "rose"
          ? "bg-rose-50 text-rose-700 border border-rose-200"
          : "bg-amber-50 text-amber-700 border border-amber-200",
      )}
    >
      <AlertTriangle size={10} />
      {children}
    </div>
  );
}

function PathBtn({
  active, onClick, title, sub,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  sub: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-xl border px-3 py-2.5 text-left transition-colors",
        active
          ? "border-violet-500 bg-violet-50 ring-2 ring-violet-200"
          : "border-[var(--color-edify-border)] bg-white hover:bg-slate-50 hover:border-slate-300",
      )}
    >
      <div
        className={cn(
          "text-[12px] font-extrabold",
          active ? "text-violet-700" : "text-slate-900",
        )}
      >
        {title}
      </div>
      <div className="text-caption muted font-semibold mt-0.5 leading-tight">
        {sub}
      </div>
    </button>
  );
}
