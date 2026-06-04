"use client";

// Per-slot execution controls for the Core Planning Board. Status- + role-aware:
// assign → complete (Salesforce ID) → IA verify → Completed, each a real action
// that mutates the CoreActivitySlot + advances the 4/4 cycle.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, RotateCcw, User, Handshake, Copy, Check, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  assignCoreSlot, completeCoreSlot, iaVerifyCoreSlot, returnCoreSlot,
} from "@/lib/actions/core-actions";
import type { CoreActivitySlot } from "@/lib/core/core-types";

export type SlotViewer = { canAssign: boolean; canExec: boolean; canIa: boolean };

const TONE: Record<string, string> = {
  "Not Planned": "bg-slate-100 text-slate-500",
  "Planned": "bg-sky-100 text-sky-700",
  "Scheduled": "bg-sky-100 text-sky-700",
  "Assigned to Partner": "bg-violet-100 text-violet-700",
  "In Progress": "bg-amber-100 text-amber-700",
  "Evidence Uploaded": "bg-amber-100 text-amber-700",
  "Awaiting IA Verification": "bg-amber-100 text-amber-700",
  "Completed": "bg-emerald-100 text-emerald-700",
  "Returned": "bg-rose-100 text-rose-700",
  "Rejected": "bg-rose-100 text-rose-700",
};

export function CoreSlotActions({ slot, viewer }: { slot: CoreActivitySlot; viewer: SlotViewer }) {
  const [mode, setMode] = useState<"none" | "complete" | "return">("none");
  const [sf, setSf] = useState("");
  const [teachers, setTeachers] = useState("");
  const [leaders, setLeaders] = useState("");
  const [reason, setReason] = useState("");
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  const isTraining = slot.activityType === "training";
  const prefix = isTraining ? "TS" : "SVE";

  function run(p: Promise<{ ok: boolean; reason?: string }>, okTitle: string, okBody: string) {
    start(async () => {
      const res = await p;
      if (res.ok) { pushToast({ tone: "success", title: okTitle, body: okBody }); setMode("none"); setSf(""); setTeachers(""); setLeaders(""); setReason(""); router.refresh(); }
      else pushToast({ tone: "warning", title: "Action failed", body: res.reason === "FORBIDDEN" ? "Not permitted for your role." : res.reason === "INVALID_INPUT" ? `Check the ${prefix}- ID${isTraining ? " + participant counts" : ""}.` : res.reason === "INVALID_STATE" ? "State changed — refresh." : "Try again." });
    });
  }

  const completeReady = sf.trim().toUpperCase().startsWith(prefix) && sf.trim().length >= 4 && (!isTraining || (!!teachers.trim() && !!leaders.trim()));

  return (
    <div className="flex items-center gap-2 flex-wrap justify-end">
      <span className={`inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-bold whitespace-nowrap ${TONE[slot.status] ?? "bg-slate-100 text-slate-500"}`}>
        {slot.status}
      </span>
      {slot.salesforceId && (
        <SfChip id={slot.salesforceId} />
      )}

      {/* IA verify/return */}
      {viewer.canIa && slot.status === "Awaiting IA Verification" && mode === "none" && (
        <>
          <button type="button" onClick={() => run(iaVerifyCoreSlot(slot.id), "IA verified", "Slot completed — cycle advanced.")} disabled={isPending}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-slate-900 text-white text-[11px] font-bold hover:bg-slate-800 disabled:opacity-50">
            {isPending ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />} Verify
          </button>
          <button type="button" onClick={() => setMode("return")} className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-rose-200 text-rose-700 text-[11px] font-bold hover:bg-rose-50">
            <RotateCcw size={11} /> Return
          </button>
        </>
      )}
      {mode === "return" && (
        <span className="inline-flex items-center gap-1.5">
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" aria-label="Return reason"
            className="h-7 w-[140px] rounded-md border border-rose-200 text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-rose-300" />
          <button type="button" disabled={isPending || reason.trim().length < 5} onClick={() => run(returnCoreSlot(slot.id, reason), "Returned", "Sent back for correction.")}
            className="h-7 px-2 rounded-md bg-rose-600 text-white text-[11px] font-bold disabled:opacity-50">Send</button>
          <button type="button" onClick={() => setMode("none")} aria-label="Cancel" className="w-6 h-7 grid place-items-center text-slate-500"><X size={12} /></button>
        </span>
      )}

      {/* Assign */}
      {viewer.canAssign && slot.owner === "unassigned" && mode === "none" && (
        <>
          <button type="button" onClick={() => run(assignCoreSlot(slot.id, { owner: "myself" }), "Assigned to you", "Plan the date next.")} disabled={isPending}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:brightness-110 disabled:opacity-50">
            <User size={11} /> Me
          </button>
          <button type="button" onClick={() => run(assignCoreSlot(slot.id, { owner: "partner", ownerName: "Partner team" }), "Assigned to partner", "The partner has been notified.")} disabled={isPending}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-[var(--color-edify-border)] text-[11px] font-bold hover:bg-[var(--color-edify-soft)]/40 disabled:opacity-50">
            <Handshake size={11} /> Partner
          </button>
        </>
      )}

      {/* Complete (enter Salesforce ID) */}
      {viewer.canExec && slot.owner !== "unassigned" && !["Awaiting IA Verification", "Completed"].includes(slot.status) && mode === "none" && (
        <button type="button" onClick={() => setMode("complete")}
          className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-emerald-600 text-white text-[11px] font-bold hover:bg-emerald-700">
          <CheckCircle2 size={11} /> Complete
        </button>
      )}
      {mode === "complete" && (
        <span className="inline-flex items-center gap-1.5 flex-wrap">
          <input value={sf} onChange={(e) => setSf(e.target.value)} placeholder={`${prefix}- Salesforce ID`} aria-label="Salesforce ID"
            className="h-7 w-[150px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-emerald-300" />
          {isTraining && (
            <>
              <input value={teachers} onChange={(e) => setTeachers(e.target.value)} type="number" min={0} placeholder="Teachers" aria-label="Teachers"
                className="h-7 w-[72px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2" />
              <input value={leaders} onChange={(e) => setLeaders(e.target.value)} type="number" min={0} placeholder="Leaders" aria-label="School leaders"
                className="h-7 w-[72px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2" />
            </>
          )}
          <button type="button" disabled={isPending || !completeReady}
            onClick={() => run(completeCoreSlot(slot.id, { salesforceId: sf.trim(), teachers: teachers ? Number(teachers) : undefined, leaders: leaders ? Number(leaders) : undefined }), "Submitted to IA", "Awaiting IA verification.")}
            className="h-7 px-2 rounded-md bg-emerald-600 text-white text-[11px] font-bold disabled:opacity-50">Submit</button>
          <button type="button" onClick={() => setMode("none")} aria-label="Cancel" className="w-6 h-7 grid place-items-center text-slate-500"><X size={12} /></button>
        </span>
      )}
    </div>
  );
}

function SfChip({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" onClick={() => { void navigator.clipboard?.writeText(id); setCopied(true); window.setTimeout(() => setCopied(false), 1200); }}
      className="inline-flex items-center gap-1 rounded border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/50 px-1.5 py-[1px] text-[10px] font-extrabold" title="Copy Salesforce ID">
      <span className="font-mono">{id}</span>{copied ? <Check size={10} className="text-emerald-600" /> : <Copy size={10} className="text-[var(--color-edify-muted)]" />}
    </button>
  );
}
