"use client";

// DisburseFormFields — reusable body of the disbursement form. Used by
// both DisburseModal (when the Accountant opens the focused dialog)
// and the inline expanded row in DisbursementQueue (when they prefer
// to act in place without losing queue context).
//
// Owns:
//   • amount, method, reference, date, notes, treasury batch state
//   • client-side validation
// Does NOT own:
//   • dialog chrome (wrapper, backdrop, close button)
//   • row chrome (avatar, gate row)
//
// Callers pass the request + a submit handler. The fields self-validate
// and disable submit until the form is valid; the same gating used by
// the modal applies inline.

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  Building2,
  CheckCircle2,
  Smartphone,
  Wallet,
} from "lucide-react";
import { fundsReceived } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";
import type {
  DisbursementMethod,
  WeeklyFundRequest,
} from "@/lib/funds/weekly-fund-types";

export type DisburseForm = {
  amountUgx: number;
  method: DisbursementMethod;
  reference: string;
  date: string;          // YYYY-MM-DD
  notes?: string;
  fundsReceivedId: string;
};

export function DisburseFormFields({
  request,
  mode,
  onCancel,
  onConfirm,
  layout = "stacked",
  submitLabel,
}: {
  request: WeeklyFundRequest;
  mode: "full" | "partial";
  onCancel?: () => void;
  onConfirm: (form: DisburseForm) => void;
  /** "stacked" — vertical form for narrow surfaces (modal, mobile).
      "grid" — 2-column grid for wider inline panels. */
  layout?: "stacked" | "grid";
  submitLabel?: string;
}) {
  const [method, setMethod] = useState<DisbursementMethod>("MobileMoney");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const [amountUgx, setAmountUgx] = useState<number>(
    () => request.requestedAmount.amount,
  );
  const [fundsReceivedId, setFundsReceivedId] = useState<string>(
    () => fundsReceived[0]?.id ?? "",
  );

  const selectedBatch = useMemo(
    () => fundsReceived.find((f) => f.id === fundsReceivedId),
    [fundsReceivedId],
  );
  const insufficient =
    selectedBatch ? amountUgx > selectedBatch.availableBalance.amount : false;
  const validReference = reference.trim().length >= 4;
  const validAmount = amountUgx > 0 && amountUgx <= request.requestedAmount.amount;
  const partialOk = mode === "partial" ? amountUgx < request.requestedAmount.amount : true;
  const canSubmit = validReference && validAmount && partialOk && !insufficient;

  const gridCls = layout === "grid"
    ? "grid grid-cols-1 sm:grid-cols-2 gap-3"
    : "flex flex-col gap-3";

  return (
    <div className="flex flex-col gap-3">
      <div className={gridCls}>
        {/* Funds source */}
        <Field label="Draw from treasury batch">
          <select
            value={fundsReceivedId}
            onChange={(e) => setFundsReceivedId(e.target.value)}
            className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          >
            {fundsReceived.map((f) => (
              <option key={f.id} value={f.id}>
                {f.reference} · available {formatMoney(f.availableBalance)}
              </option>
            ))}
          </select>
        </Field>

        {/* Amount */}
        <Field label="Amount (UGX)">
          <input
            type="number"
            min={1}
            value={amountUgx}
            onChange={(e) => setAmountUgx(Number(e.target.value))}
            className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[13px] font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
          {!validAmount && (
            <Hint tone="rose">Amount must be ≤ requested ({formatMoney(request.requestedAmount)})</Hint>
          )}
          {mode === "partial" && validAmount && !partialOk && (
            <Hint tone="rose">Partial amount must be less than the full requested amount.</Hint>
          )}
          {insufficient && (
            <Hint tone="rose">Selected treasury batch does not have enough available balance.</Hint>
          )}
        </Field>

        {/* Method — always full width */}
        <Field label="Payment method" fullWidth={layout === "grid"}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
            <MethodBtn label="Mobile Money" Icon={Smartphone} active={method === "MobileMoney"} onClick={() => setMethod("MobileMoney")} />
            <MethodBtn label="Bank"         Icon={Building2}  active={method === "BankTransfer"} onClick={() => setMethod("BankTransfer")} />
            <MethodBtn label="Cash"         Icon={Wallet}     active={method === "Cash"}         onClick={() => setMethod("Cash")} />
            <MethodBtn label="Cheque"       Icon={Banknote}   active={method === "Cheque"}       onClick={() => setMethod("Cheque")} />
          </div>
        </Field>

        {/* Reference */}
        <Field label="Transaction reference *">
          <input
            type="text"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="M-Pesa code · bank ref · cheque #"
            className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
          {reference.length > 0 && !validReference && (
            <Hint tone="rose">Reference must be at least 4 characters.</Hint>
          )}
        </Field>

        {/* Date */}
        <Field label="Date">
          <GlassDatePicker value={date} onChange={setDate} />
        </Field>

        {/* Notes — full width */}
        <Field label="Notes" fullWidth={layout === "grid"}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional — e.g. delivery reason, override note…"
            className="w-full min-h-[64px] px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </Field>
      </div>

      <footer className="flex items-center justify-end gap-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() =>
            onConfirm({
              amountUgx,
              method,
              reference: reference.trim(),
              date,
              notes: notes.trim() || undefined,
              fundsReceivedId,
            })
          }
          className={cn(
            "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-extrabold transition-colors",
            canSubmit
              ? "bg-slate-900 hover:bg-slate-800 text-white shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
              : "bg-slate-100 text-slate-400 cursor-not-allowed",
          )}
        >
          <CheckCircle2 size={12} />
          {submitLabel ?? (mode === "partial" ? "Mark Partial Disbursed" : "Mark Disbursed")}
        </button>
      </footer>
    </div>
  );
}

function Field({
  label,
  children,
  fullWidth,
}: {
  label: string;
  children: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <section className={cn(fullWidth && "sm:col-span-2")}>
      <label className="block text-[11px] font-extrabold text-slate-700 mb-1">
        {label}
      </label>
      {children}
    </section>
  );
}

function Hint({ tone, children }: { tone: "rose" | "amber"; children: React.ReactNode }) {
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

function MethodBtn({
  label, Icon, active, onClick,
}: {
  label: string;
  Icon: typeof Smartphone;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-10 px-2 rounded-lg border text-[11.5px] font-extrabold flex items-center justify-center gap-1.5 transition-colors",
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-700",
      )}
    >
      <Icon size={12} />
      {label}
    </button>
  );
}
