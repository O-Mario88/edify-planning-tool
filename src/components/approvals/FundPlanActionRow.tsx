"use client";

// FundPlanActionRow — the Approve / Return CTA row at the bottom of
// FundPlanDetail. This is the canonical wiring pattern between a UI
// button and a server action. Replicate this shape for every other
// Bucket-C surface (disbursement, reimbursement, partner verify, …).
//
// Wiring contract (in order):
//   1. `useTransition` to track the pending state of the action.
//      Buttons disable + spinner appears; users can't double-fire.
//   2. Call the server action; never trust a "success" without an `ok`.
//   3. Surface the discriminated `reason` to the user as a toast that
//      explains *what* to do next, not just "failed".
//   4. On `ok: true`, replace the local pending UI; cache revalidation
//      happens server-side, so the parent server component will pick
//      up the new status on the next render.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Eye, Loader2, RotateCcw, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  approveFundPlan,
  returnFundPlan,
  type FundPlanActionResult,
} from "@/lib/actions/fund-plan-actions";
import type { FundApprovalItem } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";

const TERMINAL_STATUSES: ReadonlySet<FundApprovalItem["status"]> = new Set([
  "Ready",
  "Returned",
]);

// Human copy for every non-ok branch. Localising this here means the
// server action can stay schema-pure; the UI owns presentation.
function reasonCopy(res: Extract<FundPlanActionResult, { ok: false }>): { title: string; body: string } {
  switch (res.reason) {
    case "FORBIDDEN":
      return { title: "Not your call", body: "Only Country Program Leads and above can approve this plan." };
    case "NOT_FOUND":
      return { title: "Plan no longer exists", body: "It may have been withdrawn or merged. Refresh the queue." };
    case "INVALID_STATE":
      return {
        title: `Already ${res.current}`,
        body: "Someone else acted on this plan first. Refresh to see the latest status.",
      };
    case "INVALID_INPUT":
      return {
        title: "Reason needed",
        body: `Add a short note (5+ characters) explaining why the plan is being returned.`,
      };
  }
}

export function FundPlanActionRow({
  planId,
  currentStatus,
  viewHref = "#",
}: {
  planId: string;
  currentStatus: FundApprovalItem["status"];
  viewHref?: string;
}) {
  const [isPending, startTransition] = useTransition();
  const [returnOpen, setReturnOpen] = useState(false);
  const [reason, setReason] = useState("");
  const { pushToast } = useDemoStore();
  const router = useRouter();

  const terminal = TERMINAL_STATUSES.has(currentStatus);

  function runApprove() {
    startTransition(async () => {
      const res = await approveFundPlan(planId);
      if (res.ok) {
        pushToast({
          tone: "success",
          title: "Plan approved",
          body: `Status is now ${res.newStatus}. Funds are queued for disbursement.`,
        });
        // Pull fresh server state so the queue badge + dashboard tiles
        // reflect the new status without a full reload. In production
        // this also re-renders any dashboard counter that depends on
        // the approval queue, because revalidatePath already busted
        // those route caches inside the server action.
        router.refresh();
      } else {
        const copy = reasonCopy(res);
        pushToast({ tone: "warning", title: copy.title, body: copy.body });
      }
    });
  }

  function runReturn() {
    startTransition(async () => {
      const res = await returnFundPlan(planId, reason);
      if (res.ok) {
        pushToast({
          tone: "info",
          title: "Plan returned",
          body: "The CCEO will see the reason in their inbox and can resubmit.",
        });
        setReturnOpen(false);
        setReason("");
        router.refresh();
      } else {
        const copy = reasonCopy(res);
        pushToast({ tone: "warning", title: copy.title, body: copy.body });
      }
    });
  }

  return (
    <div className="pt-3 border-t border-[#eef2f4]">
      {/* Primary action row */}
      <div className="grid grid-cols-3 gap-2">
        <a
          href={viewHref}
          className="inline-flex items-center justify-center gap-1.5 h-10 rounded-xl bg-white border border-[var(--color-edify-border)] text-[12px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
        >
          <Eye size={13} />
          View Full Plan
        </a>
        <button
          type="button"
          onClick={runApprove}
          disabled={isPending || terminal}
          aria-disabled={isPending || terminal}
          className={cn(
            "btn btn-primary inline-flex items-center justify-center gap-1.5 h-10 rounded-xl text-body font-extrabold",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
          title={terminal ? `Plan is already ${currentStatus}` : "Approve Plan"}
        >
          {isPending && !returnOpen ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
          Approve
        </button>
        <button
          type="button"
          onClick={() => setReturnOpen((v) => !v)}
          disabled={isPending || terminal}
          aria-disabled={isPending || terminal}
          aria-expanded={returnOpen}
          className={cn(
            "inline-flex items-center justify-center gap-1.5 h-10 rounded-xl bg-white border text-[12px] font-semibold transition-colors",
            returnOpen
              ? "border-rose-300 bg-rose-50 text-rose-800"
              : "border-rose-200 text-rose-700 hover:bg-rose-50",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
          title={terminal ? `Plan is already ${currentStatus}` : "Return for correction"}
        >
          <RotateCcw size={13} />
          Return
        </button>
      </div>

      {/* Inline reason input — cheaper UX than a modal, and the
          reason stays visible in the same scroll context as the plan.
          Auto-collapses on success or on explicit dismiss. */}
      {returnOpen && (
        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/40 p-3 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <label htmlFor={`return-reason-${planId}`} className="text-[11.5px] font-extrabold text-rose-900">
              Reason for returning (CCEO sees this)
            </label>
            <button
              type="button"
              onClick={() => { setReturnOpen(false); setReason(""); }}
              aria-label="Cancel return"
              className="inline-flex items-center justify-center w-6 h-6 rounded-md text-rose-700 hover:bg-rose-100"
            >
              <X size={12} />
            </button>
          </div>
          <textarea
            id={`return-reason-${planId}`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="e.g. Cluster training quantities don't match the May cluster plan — confirm before re-submitting."
            className="w-full rounded-lg border border-rose-200 bg-white text-[12px] p-2 focus:outline-none focus:ring-2 focus:ring-rose-300"
          />
          <div className="flex items-center justify-between gap-2">
            <span className={cn("text-[10.5px] font-semibold", reason.trim().length < 5 ? "text-rose-700" : "muted")}>
              {reason.trim().length < 5
                ? `Need ${5 - reason.trim().length} more character${5 - reason.trim().length === 1 ? "" : "s"}`
                : `${reason.trim().length} chars`}
            </span>
            <button
              type="button"
              onClick={runReturn}
              disabled={isPending || reason.trim().length < 5}
              className="inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-[11.5px] font-extrabold disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_4px_10px_-4px_rgba(225,29,72,0.5)]"
            >
              {isPending ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
              Send return
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
