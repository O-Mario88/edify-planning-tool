"use client";

// Onboard / Reject controls for the Core Onboarding Queue. Onboarding creates
// the CoreSchoolProfile + CorePlan + 4 priority interventions + 8 activity slots
// and flips the school to Core (a real transition, not a label change).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { onboardCoreSchool, rejectCoreCandidate } from "@/lib/actions/core-actions";

export function CoreOnboardControls({ schoolId, schoolName }: { schoolId: string; schoolName: string }) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function onboard() {
    start(async () => {
      const res = await onboardCoreSchool(schoolId);
      if (res.ok) {
        pushToast({ tone: "success", title: "Onboarded as Core", body: `${schoolName} — core plan + 4 visits + 4 trainings created.` });
        router.refresh();
      } else {
        pushToast({
          tone: "warning", title: "Couldn't onboard",
          body: res.reason === "FORBIDDEN" ? "Only CD/PL/IA/Admin can onboard."
            : res.reason === "NOT_VERIFIED" ? "Verify the candidate first."
            : res.reason === "ALREADY_CORE" ? "Already a core school." : "Candidate not found — refresh.",
        });
      }
    });
  }

  function reject() {
    start(async () => {
      const res = await rejectCoreCandidate(schoolId, reason);
      if (res.ok) {
        pushToast({ tone: "info", title: "Candidate rejected", body: schoolName });
        setRejectOpen(false); setReason("");
        router.refresh();
      } else {
        pushToast({ tone: "warning", title: "Couldn't reject", body: "Add a short reason (5+ chars)." });
      }
    });
  }

  return (
    <div className="inline-flex items-center gap-2">
      {rejectOpen ? (
        <span className="inline-flex items-center gap-1.5">
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" aria-label="Reject reason"
            className="h-8 w-[150px] rounded-md border border-rose-200 bg-white text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-rose-300"
            onKeyDown={(e) => { if (e.key === "Enter" && reason.trim().length >= 5) reject(); }} />
          <button type="button" onClick={reject} disabled={isPending || reason.trim().length < 5}
            className="inline-flex items-center h-8 px-2 rounded-md bg-rose-600 text-white text-[11px] font-bold hover:bg-rose-700 disabled:opacity-50">Reject</button>
          <button type="button" onClick={() => { setRejectOpen(false); setReason(""); }} aria-label="Cancel"
            className="inline-flex items-center justify-center w-6 h-8 rounded-md text-slate-500 hover:bg-slate-100"><X size={12} /></button>
        </span>
      ) : (
        <>
          <button type="button" onClick={onboard} disabled={isPending}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-bold hover:brightness-110 disabled:opacity-50">
            {isPending ? <Loader2 size={12} className="animate-spin" /> : <GraduationCap size={13} />} Onboard as Core
          </button>
          <button type="button" onClick={() => setRejectOpen(true)} disabled={isPending}
            className="text-[11px] font-semibold text-rose-700 hover:underline">Reject</button>
        </>
      )}
    </div>
  );
}
