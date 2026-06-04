"use client";

// Inline "mark verified" control for an open SSA verification todo. Captures
// the new SSA Verification ID and calls the completeSsaVerificationTodo action.
// Same wiring contract as FundPlanActionRow (useTransition + toast + refresh).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { completeSsaVerificationTodo } from "@/lib/actions/ssa-todo-actions";

export function SsaTodoCompleteCell({ todoId, schoolName }: { todoId: string; schoolName: string }) {
  const [open, setOpen] = useState(false);
  const [ssaId, setSsaId] = useState("");
  const [isPending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function submit() {
    startTransition(async () => {
      const res = await completeSsaVerificationTodo(todoId, ssaId);
      if (res.ok) {
        pushToast({
          tone: "success",
          title: "SSA verified",
          body: `${schoolName} — ID ${res.ssaVerificationId} recorded · ${res.flag}.`,
        });
        setOpen(false);
        setSsaId("");
        router.refresh();
      } else {
        const copy =
          res.reason === "FORBIDDEN" ? "You're not permitted to verify SSA todos."
          : res.reason === "DUPLICATE" ? "This todo is already verified."
          : res.reason === "NOT_FOUND" ? "Todo no longer exists — refresh."
          : "Enter a valid SSA Verification ID (3+ characters).";
        pushToast({ tone: "warning", title: "Couldn't verify", body: copy });
      }
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-bold hover:brightness-110"
      >
        <CheckCircle2 size={12} /> Mark verified
      </button>
    );
  }

  return (
    <div className="inline-flex items-center gap-1.5">
      <input
        value={ssaId}
        onChange={(e) => setSsaId(e.target.value)}
        placeholder="New SSA Verification ID"
        aria-label={`SSA Verification ID for ${schoolName}`}
        className="h-8 w-[180px] rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] px-2 focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
        onKeyDown={(e) => { if (e.key === "Enter" && ssaId.trim().length >= 3) submit(); }}
      />
      <button
        type="button"
        onClick={submit}
        disabled={isPending || ssaId.trim().length < 3}
        className="inline-flex items-center justify-center h-8 px-2.5 rounded-lg bg-emerald-600 text-white text-[11.5px] font-bold hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isPending ? <Loader2 size={12} className="animate-spin" /> : "Save"}
      </button>
      <button
        type="button"
        onClick={() => { setOpen(false); setSsaId(""); }}
        aria-label="Cancel"
        className="inline-flex items-center justify-center w-7 h-8 rounded-lg text-slate-500 hover:bg-slate-100"
      >
        <X size={13} />
      </button>
    </div>
  );
}
