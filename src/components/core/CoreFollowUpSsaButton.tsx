"use client";

// Follow-Up SSA upload (IA) for a completed core plan. Captures the 8
// intervention scores, calls uploadCoreFollowUpSsa → runs the real
// baseline-vs-new impact computation + champion eligibility.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ClipboardCheck, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { SSA_INTERVENTION_AREAS, type SsaInterventionArea } from "@/lib/intake/intake-core";
import { uploadCoreFollowUpSsa } from "@/lib/actions/core-actions";

export function CoreFollowUpSsaButton({ planId }: { planId: string }) {
  const [open, setOpen] = useState(false);
  const [scores, setScores] = useState<Record<string, string>>({});
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  const filled = SSA_INTERVENTION_AREAS.every((a) => {
    const v = Number(scores[a]);
    return scores[a] !== undefined && scores[a] !== "" && Number.isFinite(v) && v >= 0 && v <= 10;
  });

  function submit() {
    const payload: Partial<Record<SsaInterventionArea, number>> = {};
    for (const a of SSA_INTERVENTION_AREAS) payload[a] = Number(scores[a]);
    start(async () => {
      const res = await uploadCoreFollowUpSsa(planId, payload);
      if (res.ok) {
        pushToast({ tone: "success", title: "Impact measured", body: `Avg SSA change ${res.averageChange >= 0 ? "+" : ""}${res.averageChange}.${res.championCandidate ? " Potential Champion." : ""}` });
        setOpen(false); setScores({});
        router.refresh();
      } else {
        pushToast({ tone: "warning", title: "Couldn't upload", body: res.reason === "NOT_READY" ? "Package isn't complete yet." : res.reason === "DUPLICATE" ? "Follow-up SSA already on file." : res.reason === "FORBIDDEN" ? "IA/Admin only." : "Enter all 8 scores (0–10)." });
      }
    });
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-bold hover:brightness-110">
        <ClipboardCheck size={13} /> Upload Follow-Up SSA
      </button>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/30 p-3 mt-2">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[12px] font-extrabold tracking-tight">Follow-Up SSA — 8 intervention scores (0–10)</div>
        <button type="button" onClick={() => setOpen(false)} aria-label="Cancel" className="w-6 h-6 grid place-items-center text-slate-500 hover:bg-slate-100 rounded-md"><X size={13} /></button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {SSA_INTERVENTION_AREAS.map((a) => (
          <label key={a} className="block">
            <span className="block text-[10px] muted font-semibold leading-tight truncate" title={a}>{a}</span>
            <input type="number" min={0} max={10} value={scores[a] ?? ""} onChange={(e) => setScores((s) => ({ ...s, [a]: e.target.value }))}
              className="w-full h-8 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] px-2 font-bold tabular focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30" />
          </label>
        ))}
      </div>
      <div className="flex justify-end mt-2.5">
        <button type="button" onClick={submit} disabled={isPending || !filled}
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-emerald-600 text-white text-[11.5px] font-bold hover:bg-emerald-700 disabled:opacity-50">
          {isPending ? <Loader2 size={12} className="animate-spin" /> : <ClipboardCheck size={12} />} Compute impact
        </button>
      </div>
    </div>
  );
}
