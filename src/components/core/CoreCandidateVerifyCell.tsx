"use client";

// Inline "Verify" control for a core candidate — captures the SSA Verification
// ID and calls verifyCoreCandidate, which records the verification and pushes
// the school into the Core Onboarding Queue (no stop-at-notification).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { verifyCoreCandidate } from "@/lib/actions/core-actions";

export function CoreCandidateVerifyCell({ schoolId, schoolName }: { schoolId: string; schoolName: string }) {
  const [open, setOpen] = useState(false);
  const [vid, setVid] = useState("");
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function submit() {
    start(async () => {
      const res = await verifyCoreCandidate(schoolId, vid);
      if (res.ok) {
        pushToast({ tone: "success", title: "Verified Potential Core", body: `${schoolName} → Core Onboarding Queue.` });
        setOpen(false); setVid("");
        router.refresh();
      } else {
        pushToast({
          tone: "warning", title: "Couldn't verify",
          body: res.reason === "FORBIDDEN" ? "Your role can't verify candidates."
            : res.reason === "DUPLICATE" ? "Already verified."
            : res.reason === "NOT_FOUND" ? "Candidate no longer exists — refresh."
            : "Enter a valid SSA Verification ID (3+ chars).",
        });
      }
    });
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-bold hover:brightness-110">
        <CheckCircle2 size={12} /> Verify
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <input
        value={vid} onChange={(e) => setVid(e.target.value)} placeholder="SSA Verification ID"
        aria-label={`SSA Verification ID for ${schoolName}`}
        className="h-8 w-[170px] rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] px-2 focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
        onKeyDown={(e) => { if (e.key === "Enter" && vid.trim().length >= 3) submit(); }}
      />
      <button type="button" onClick={submit} disabled={isPending || vid.trim().length < 3}
        className="inline-flex items-center justify-center h-8 px-2.5 rounded-lg bg-emerald-600 text-white text-[11.5px] font-bold hover:bg-emerald-700 disabled:opacity-50">
        {isPending ? <Loader2 size={12} className="animate-spin" /> : "Save"}
      </button>
      <button type="button" onClick={() => { setOpen(false); setVid(""); }} aria-label="Cancel"
        className="inline-flex items-center justify-center w-7 h-8 rounded-lg text-slate-500 hover:bg-slate-100">
        <X size={13} />
      </button>
    </span>
  );
}
