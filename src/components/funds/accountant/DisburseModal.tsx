"use client";

import { X } from "lucide-react";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";
import { DisburseFormFields, type DisburseForm } from "./DisburseFormFields";

// Accountant Disburse Modal.
//
// Thin dialog chrome around the shared DisburseFormFields. The same
// form is also rendered inline inside the DisbursementQueue expanded
// row, so the modal exists only for the "focused dialog" preference —
// keystroke flow + dimming background is the same as before.
export function DisburseModal({
  open,
  request,
  onClose,
  onConfirm,
  mode = "full",
}: {
  open: boolean;
  request: WeeklyFundRequest | undefined;
  onClose: () => void;
  onConfirm: (form: DisburseForm) => void;
  mode?: "full" | "partial";
}) {
  if (!open || !request) return null;
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
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
      />
      <article className="card relative w-full max-w-lg p-4 max-h-[90vh] overflow-y-auto">
        <header className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900">
              {mode === "partial" ? "Partial disbursement" : "Disburse funds"}
            </h2>
            <div className="text-[11px] muted mt-0.5 leading-tight truncate">
              {request.staffName} · Week {request.period.weekOfMonth} · {request.district}
            </div>
            <div className="text-caption muted font-semibold mt-0.5">
              Requested: <span className="font-extrabold text-slate-700 tabular">{formatMoney(request.requestedAmount)}</span>
            </div>
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

        <DisburseFormFields
          key={request.id}
          request={request}
          mode={mode}
          onCancel={onClose}
          onConfirm={onConfirm}
          layout="stacked"
        />
      </article>
    </div>
  );
}

export type { DisburseForm } from "./DisburseFormFields";
