"use client";

// Client islands for the Data Validation queue row actions: Validate,
// Send for review, and Reject (with inline reason). Each calls its server
// action (actor resolved server-side), toasts the discriminated result,
// and refreshes so the next render shows the new status.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  validateBatch,
  sendBatchForReview,
  rejectImport,
  type BatchActionResult,
} from "@/lib/data-intake-actions";

function failCopy(res: Extract<BatchActionResult, { ok: false }>): string {
  switch (res.reason) {
    case "FORBIDDEN": return "Your role can't act on import batches.";
    case "NOT_FOUND": return "Batch no longer exists — refresh.";
    case "WRONG_STATUS": return "Someone changed this batch first — refresh.";
    case "INVALID_INPUT": return "Add a short reason (5+ characters).";
  }
}

export function ValidateBatchButton({ batchId }: { batchId: string }) {
  return (
    <TransitionLink batchId={batchId} label="Validate →" run={validateBatch}
      successTitle="Batch validated" successBody="Schema + business-rule checks passed." />
  );
}

export function SendForReviewButton({ batchId }: { batchId: string }) {
  return (
    <TransitionLink batchId={batchId} label="Send for review →" run={sendBatchForReview}
      successTitle="Sent to reviewer" successBody="Routed for approval." />
  );
}

function TransitionLink({
  batchId, label, run, successTitle, successBody,
}: {
  batchId: string;
  label: string;
  run: (id: string) => Promise<BatchActionResult>;
  successTitle: string;
  successBody: string;
}) {
  const { pushToast } = useDemoStore();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  function go() {
    startTransition(async () => {
      const res = await run(batchId);
      if (res.ok) {
        pushToast({ tone: "success", title: successTitle, body: successBody });
        router.refresh();
      } else {
        pushToast({ tone: "warning", title: "Couldn't update batch", body: failCopy(res) });
      }
    });
  }
  return (
    <button type="button" onClick={go} disabled={pending}
      className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline disabled:opacity-55 inline-flex items-center gap-1">
      {pending && <Loader2 size={11} className="animate-spin" />}
      {label}
    </button>
  );
}

export function RejectBatchButton({ batchId }: { batchId: string }) {
  const { pushToast } = useDemoStore();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, startTransition] = useTransition();

  function go() {
    startTransition(async () => {
      const res = await rejectImport(batchId, reason);
      if (res.ok) {
        pushToast({ tone: "info", title: "Batch rejected", body: "The uploader will see the reason and can re-submit." });
        setOpen(false);
        setReason("");
        router.refresh();
      } else {
        pushToast({ tone: "warning", title: "Couldn't reject", body: failCopy(res) });
      }
    });
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="text-[11px] font-semibold text-rose-700 hover:underline">
        Reject →
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason"
        aria-label="Rejection reason"
        className="h-7 w-[150px] rounded-md border border-rose-200 bg-white text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-rose-300"
        onKeyDown={(e) => { if (e.key === "Enter" && reason.trim().length >= 5) go(); }}
      />
      <button type="button" onClick={go} disabled={pending || reason.trim().length < 5}
        className="inline-flex items-center h-7 px-2 rounded-md bg-rose-600 text-white text-[11px] font-bold hover:bg-rose-700 disabled:opacity-50">
        {pending ? <Loader2 size={11} className="animate-spin" /> : "Reject"}
      </button>
      <button type="button" onClick={() => { setOpen(false); setReason(""); }} aria-label="Cancel"
        className="inline-flex items-center justify-center w-6 h-7 rounded-md text-slate-500 hover:bg-slate-100">
        <X size={12} />
      </button>
    </span>
  );
}
