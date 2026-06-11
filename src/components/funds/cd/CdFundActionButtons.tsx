"use client";

// Approve / Return for a single CD-tier fund request. The CD queue's
// inline buttons were dead stubs (onClick = stopPropagation only) — this
// wires them to the live, role-checked weekly-fund actions so the CD can
// actually action PL / IA / Accountant / SP requests. Return opens an
// inline reason field (5+ chars) like the canonical FundPlanActionRow.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { approveFundRequest, returnFundRequest } from "@/lib/actions/weekly-fund-actions";

export function CdFundActionButtons({ reqId }: { reqId: string }) {
  const [pending, startTransition] = useTransition();
  const [returnOpen, setReturnOpen] = useState(false);
  const [reason, setReason] = useState("");
  const { pushToast } = useDemoStore();
  const router = useRouter();
  const valid = reason.trim().length >= 5;

  function runApprove() {
    startTransition(async () => {
      const res = await approveFundRequest(reqId);
      if (res.ok) pushToast({ tone: "success", title: "Request approved", body: "Approved — queued for disbursement." });
      else pushToast({ tone: "warning", title: "Couldn't approve", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  function runReturn() {
    startTransition(async () => {
      const res = await returnFundRequest(reqId, reason.trim());
      if (res.ok) { pushToast({ tone: "info", title: "Request returned", body: "The requester sees the reason and can resubmit." }); setReturnOpen(false); setReason(""); }
      else pushToast({ tone: "warning", title: "Couldn't return", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }

  return (
    <span className="inline-flex items-center gap-1 ml-1" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setReturnOpen((v) => !v)}
        disabled={pending}
        aria-expanded={returnOpen}
        className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-rose-200 bg-rose-50 hover:bg-rose-100 text-caption font-extrabold text-rose-700 disabled:opacity-50"
      >
        <XCircle size={10} /> Return
      </button>
      <button
        type="button"
        onClick={runApprove}
        disabled={pending}
        className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-caption font-extrabold disabled:opacity-50"
      >
        {pending ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />} Approve
      </button>

      {returnOpen && (
        <span className="inline-flex items-center gap-1">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (5+ chars)"
            aria-label="Return reason"
            className="h-7 w-44 rounded-md border border-rose-200 bg-white text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-rose-300"
            onKeyDown={(e) => { if (e.key === "Enter" && valid) runReturn(); }}
          />
          <button
            type="button"
            onClick={runReturn}
            disabled={pending || !valid}
            className="inline-flex items-center h-7 px-2 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-caption font-extrabold disabled:opacity-50"
          >
            Send
          </button>
        </span>
      )}
    </span>
  );
}
