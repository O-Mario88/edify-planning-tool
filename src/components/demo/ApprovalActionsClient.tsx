"use client";

import { useState } from "react";
import {
  CheckCircle2,
  RotateCcw,
  Edit3,
  Send,
  Loader2,
  AlertTriangle,
  X,
} from "lucide-react";
import { useDemoStore, type DemoApprovalAction } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Drop-in client component used on the submission detail page. Renders the
// role-correct action buttons + modal forms + applies the action to the
// demo overlay store. Status moves, audit gets appended, toast fires.

type Role = "Program Lead" | "Country Director" | "RVP";

export function ApprovalActionsClient({
  submissionId,
  stage,
  requestedBudget,
  amendedBudget,
}: {
  submissionId:     string;
  stage:            Role;
  requestedBudget:  number;
  amendedBudget?:   number;
}) {
  const { applyAction, state } = useDemoStore();
  const overlay = state.submissions[submissionId];
  const overlayStatus = overlay?.status;

  // If the demo overlay already advanced the status past this stage, hide actions.
  const isPastStage =
    (stage === "Program Lead"     && overlayStatus && !overlayStatus.includes("Program Lead")) ||
    (stage === "Country Director" && overlayStatus?.startsWith("Submitted to RVP")) ||
    (stage === "RVP"              && overlayStatus === "Final Approved");

  if (isPastStage) {
    return (
      <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 inline-flex items-center gap-2 text-[11.5px] text-emerald-800">
        <CheckCircle2 size={12} />
        Action taken this demo session — new status: <span className="font-extrabold">{overlayStatus}</span>
      </div>
    );
  }

  return (
    <ActionsRow
      submissionId={submissionId}
      stage={stage}
      onApply={applyAction}
      requestedBudget={requestedBudget}
      amendedBudget={amendedBudget}
    />
  );
}

function ActionsRow({
  submissionId, stage, onApply, requestedBudget, amendedBudget,
}: {
  submissionId: string;
  stage: Role;
  onApply: (id: string, action: DemoApprovalAction, payload?: { amount?: number; reason?: string; comment?: string }) => void;
  requestedBudget: number;
  amendedBudget?: number;
}) {
  const [modal, setModal] = useState<null | "return" | "amend" | "approve" | "rvpFinal" | "submitRvp">(null);

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap">
        {stage === "Program Lead" && (
          <button
            type="button"
            onClick={() => setModal("approve")}
            className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-semibold inline-flex items-center gap-1.5"
          >
            <CheckCircle2 size={13} />
            Approve Plan + budget
          </button>
        )}
        {stage === "Country Director" && (
          <>
            <button
              type="button"
              onClick={() => setModal("approve")}
              className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-semibold inline-flex items-center gap-1.5"
            >
              <CheckCircle2 size={13} />
              Approve
            </button>
            <button
              type="button"
              onClick={() => setModal("amend")}
              className="h-9 px-3 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-body font-semibold inline-flex items-center gap-1.5"
            >
              <Edit3 size={13} />
              Amend budget
            </button>
            <button
              type="button"
              onClick={() => setModal("submitRvp")}
              className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5"
            >
              <Send size={13} />
              Submit to RVP
            </button>
          </>
        )}
        {stage === "RVP" && (
          <button
            type="button"
            onClick={() => setModal("rvpFinal")}
            className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-semibold inline-flex items-center gap-1.5"
          >
            <CheckCircle2 size={13} />
            Final approve
          </button>
        )}
        <button
          type="button"
          onClick={() => setModal("return")}
          className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5"
        >
          <RotateCcw size={13} />
          Return
        </button>
      </div>

      {modal && (
        <Modal
          mode={modal}
          stage={stage}
          requestedBudget={requestedBudget}
          amendedBudget={amendedBudget}
          onClose={() => setModal(null)}
          onConfirm={(payload) => {
            const action = pickAction(modal, stage);
            onApply(submissionId, action, payload);
            setModal(null);
          }}
        />
      )}
    </>
  );
}

function pickAction(
  mode: "return" | "amend" | "approve" | "rvpFinal" | "submitRvp",
  stage: Role,
): DemoApprovalAction {
  if (mode === "approve" && stage === "Program Lead")     return "PL_APPROVE";
  if (mode === "approve" && stage === "Country Director") return "CD_APPROVE";
  if (mode === "rvpFinal")                                 return "RVP_FINAL_APPROVE";
  if (mode === "amend")                                    return "CD_AMEND";
  if (mode === "submitRvp")                                return "CD_SUBMIT_TO_RVP";
  // return
  if (stage === "Program Lead")     return "PL_RETURN";
  if (stage === "Country Director") return "CD_RETURN";
  return "RVP_RETURN";
}

function Modal({
  mode, stage, requestedBudget, amendedBudget, onClose, onConfirm,
}: {
  mode: "return" | "amend" | "approve" | "rvpFinal" | "submitRvp";
  stage: Role;
  requestedBudget: number;
  amendedBudget?: number;
  onClose: () => void;
  onConfirm: (payload?: { amount?: number; reason?: string; comment?: string }) => void;
}) {
  const initialAmount = amendedBudget ?? requestedBudget;
  const [amount, setAmount]   = useState<number>(Math.round(initialAmount * 0.85));
  const [reason, setReason]   = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy]       = useState(false);

  const isReturn = mode === "return";
  const isAmend  = mode === "amend";
  const requiresReason = isReturn || isAmend;

  const title =
    mode === "approve"    ? `${stage} approval` :
    mode === "rvpFinal"   ? "RVP final approval" :
    mode === "submitRvp"  ? "Submit to RVP" :
    mode === "amend"      ? "Amend monthly budget" :
                            `Return to ${stage === "RVP" ? "Country Director" : stage === "Country Director" ? "Program Lead" : "Staff"}`;

  const confirm = () => {
    if (requiresReason && reason.trim().length < 6) return;
    setBusy(true);
    // Tiny optimistic delay so the loading state is visible.
    window.setTimeout(() => {
      onConfirm({
        amount:  isAmend ? amount : undefined,
        reason:  reason.trim() || undefined,
        comment: comment.trim() || undefined,
      });
    }, 350);
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm grid place-items-center px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[460px] rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-edify-border)]">
          <h2 className="text-body-lg font-extrabold tracking-tight">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="h-8 w-8 rounded-md grid place-items-center hover:bg-[var(--color-edify-soft)]/60"
            aria-label="Close"
          >
            <X size={14} className="text-[var(--color-edify-muted)]" />
          </button>
        </header>

        <div className="px-4 py-3 space-y-3">
          {isAmend && (
            <div>
              <label className="text-[11px] font-extrabold uppercase tracking-wide muted">Amended amount (UGX)</label>
              <input
                type="number"
                value={amount}
                min={0}
                onChange={(e) => setAmount(Number(e.target.value))}
                className="mt-1 w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-[13px] tabular focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
              <div className="text-caption muted mt-1">
                Original requested: <span className="line-through">UGX {requestedBudget.toLocaleString()}</span> — original is preserved permanently.
              </div>
            </div>
          )}

          {requiresReason && (
            <div>
              <label className="text-[11px] font-extrabold uppercase tracking-wide muted">
                Reason <span className="text-rose-700">required</span>
              </label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                placeholder={isAmend ? "Why are you amending the budget?" : "Why are you returning this submission?"}
                className="mt-1 w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
              {reason.trim().length < 6 && (
                <div className="text-caption text-rose-700 mt-1 inline-flex items-center gap-1">
                  <AlertTriangle size={10} />
                  Reason must be at least 6 characters.
                </div>
              )}
            </div>
          )}

          <div>
            <label className="text-[11px] font-extrabold uppercase tracking-wide muted">Optional comment</label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              placeholder="Any additional context for the audit trail…"
              className="mt-1 w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </div>

          <div className="rounded-lg bg-[var(--color-edify-soft)]/40 px-3 py-2 text-caption muted">
            This action will append to the audit trail with timestamp + actor + previous-status → new-status. The original requested budget is never overwritten.
          </div>
        </div>

        <footer className="px-4 py-3 border-t border-[var(--color-edify-border)] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={busy || (requiresReason && reason.trim().length < 6)}
            className={cn(
              "h-9 px-3 rounded-xl text-white text-body font-semibold inline-flex items-center gap-1.5",
              isReturn ? "bg-rose-500 hover:bg-rose-600" :
              isAmend  ? "bg-amber-500 hover:bg-amber-600" :
                         "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]",
              busy && "opacity-70 cursor-not-allowed",
            )}
          >
            {busy
              ? <Loader2 size={12} className="animate-spin" />
              : isReturn ? <RotateCcw size={12} />
                : isAmend  ? <Edit3   size={12} />
                  : <CheckCircle2 size={12} />}
            {busy ? "Working…" : isReturn ? "Confirm Return" : isAmend ? "Save Amendment" : "Confirm"}
          </button>
        </footer>
      </div>
    </div>
  );
}
