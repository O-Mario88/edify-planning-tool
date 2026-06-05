"use client";

// Per-slot execution controls for the Core Planning Board. The full staged
// workflow, status- + role-aware:
//   assign → schedule → start → upload evidence → (partner: reviewer accepts)
//   → complete (Salesforce ID) → PL sign-off (CCEO visits) → IA verify
//   → accountant pay (partner). Each button is a real action mutating the slot.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2, Loader2, RotateCcw, User, Handshake, Copy, Check, X, ShieldCheck,
  Wallet, Play, CalendarClock, Upload, ClipboardCheck,
} from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  assignCoreSlot, completeCoreSlot, iaVerifyCoreSlot, returnCoreSlot,
  plVerifyCoreSlot, accountantConfirmCoreSlot, startCoreSlot, scheduleCoreSlot,
  uploadCoreEvidence, acceptCoreEvidence, returnCoreEvidence,
} from "@/lib/actions/core-actions";
import { listPartners } from "@/lib/partners-store";
import type { CoreActivitySlot } from "@/lib/core/core-types";

export type SlotViewer = { canAssign: boolean; canExec: boolean; canIa: boolean; canPl?: boolean; canAccountant?: boolean };

const TONE: Record<string, string> = {
  "Not Planned": "bg-slate-100 text-slate-500",
  "Planned": "bg-sky-100 text-sky-700",
  "Scheduled": "bg-sky-100 text-sky-700",
  "Rescheduled": "bg-sky-100 text-sky-700",
  "Assigned to Partner": "bg-violet-100 text-violet-700",
  "Partner Scheduled": "bg-violet-100 text-violet-700",
  "In Progress": "bg-amber-100 text-amber-700",
  "Evidence Uploaded": "bg-amber-100 text-amber-700",
  "Evidence Accepted": "bg-teal-100 text-teal-700",
  "Awaiting IA Verification": "bg-amber-100 text-amber-700",
  "Completed": "bg-emerald-100 text-emerald-700",
  "Returned": "bg-rose-100 text-rose-700",
  "Rejected": "bg-rose-100 text-rose-700",
};

const MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"];

type Mode = "none" | "complete" | "return" | "partner" | "schedule" | "evidence" | "evreturn";

export function CoreSlotActions({ slot, viewer }: { slot: CoreActivitySlot; viewer: SlotViewer }) {
  const [mode, setMode] = useState<Mode>("none");
  const [sf, setSf] = useState("");
  const [teachers, setTeachers] = useState("");
  const [leaders, setLeaders] = useState("");
  const [reason, setReason] = useState("");
  const [partnerName, setPartnerName] = useState("");
  const [month, setMonth] = useState("Oct");
  const [week, setWeek] = useState("1");
  const [evidenceUri, setEvidenceUri] = useState("");
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  const isTraining = slot.activityType === "training";
  const prefix = isTraining ? "TS" : "SVE";
  const isPartnerSlot = !!slot.assignedPartnerId || slot.owner === "partner" || slot.owner === "partner_facilitator";
  const ownerAssigned = slot.owner !== "unassigned";

  function run(p: Promise<{ ok: boolean; reason?: string }>, okTitle: string, okBody: string) {
    start(async () => {
      const res = await p;
      if (res.ok) {
        pushToast({ tone: "success", title: okTitle, body: okBody });
        setMode("none"); setSf(""); setTeachers(""); setLeaders(""); setReason(""); setPartnerName(""); setEvidenceUri("");
        router.refresh();
      } else {
        pushToast({ tone: "warning", title: "Action failed", body:
          res.reason === "FORBIDDEN" ? "Not permitted for your role."
          : res.reason === "INVALID_INPUT" ? `Check the ${prefix}- ID${isTraining ? " + participant counts" : ""}.`
          : res.reason === "INVALID_STATE" ? "State changed — refresh." : "Try again." });
      }
    });
  }

  const completeReady = sf.trim().toUpperCase().startsWith(prefix) && sf.trim().length >= 4 && (!isTraining || (!!teachers.trim() && !!leaders.trim()));

  // Which sub-steps are available right now.
  const terminal = slot.status === "Completed";
  const awaitingIa = slot.status === "Awaiting IA Verification";
  const canSchedule = viewer.canExec && ownerAssigned && !terminal && !awaitingIa && ["Not Planned", "Planned", "Scheduled", "Rescheduled", "Assigned to Partner", "Partner Scheduled", "In Progress"].includes(slot.status);
  const canStart = viewer.canExec && ownerAssigned && ["Planned", "Scheduled", "Rescheduled", "Partner Scheduled"].includes(slot.status);
  const canUploadEvidence = viewer.canExec && ownerAssigned && slot.status === "In Progress";
  const canReviewEvidence = viewer.canAssign && isPartnerSlot && slot.status === "Evidence Uploaded";
  const canComplete = viewer.canExec && ownerAssigned && (
    isPartnerSlot ? slot.status === "Evidence Accepted"
      : ["In Progress", "Evidence Uploaded", "Planned", "Scheduled", "Rescheduled"].includes(slot.status)
  );

  return (
    <div className="flex items-center gap-2 flex-wrap justify-end">
      <span className={`inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-bold whitespace-nowrap ${TONE[slot.status] ?? "bg-slate-100 text-slate-500"}`}>
        {slot.status}
      </span>
      {slot.scheduledFor && !terminal && <span className="text-[10px] muted whitespace-nowrap">{slot.scheduledFor}</span>}
      {slot.salesforceId && <SfChip id={slot.salesforceId} />}

      {/* PL sign-off (CCEO visits) */}
      {slot.plVerificationStatus === "Pending" && (
        viewer.canPl ? (
          <button type="button" disabled={isPending} onClick={() => run(plVerifyCoreSlot(slot.id), "PL signed off", "Sent to IA for verification.")}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-indigo-600 text-white text-[11px] font-bold hover:bg-indigo-700 disabled:opacity-50">
            {isPending ? <Loader2 size={11} className="animate-spin" /> : <ShieldCheck size={11} />} PL verify
          </button>
        ) : (
          <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded text-[10px] font-bold bg-indigo-50 text-indigo-700"><ShieldCheck size={10} /> Awaiting PL</span>
        )
      )}

      {/* Accountant confirmation (partner-delivered, IA-verified) */}
      {viewer.canAccountant && slot.iaVerificationStatus === "Verified" && slot.assignedPartnerId && slot.accountantStatus !== "Confirmed" && (
        <button type="button" disabled={isPending} onClick={() => run(accountantConfirmCoreSlot(slot.id), "Payment confirmed", "Partner payment cleared.")}
          className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-teal-600 text-white text-[11px] font-bold hover:bg-teal-700 disabled:opacity-50">
          {isPending ? <Loader2 size={11} className="animate-spin" /> : <Wallet size={11} />} Confirm pay
        </button>
      )}

      {/* IA verify/return */}
      {viewer.canIa && awaitingIa && slot.plVerificationStatus !== "Pending" && mode === "none" && (
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

      {/* Assign */}
      {viewer.canAssign && slot.owner === "unassigned" && mode === "none" && (
        <>
          <button type="button" onClick={() => run(assignCoreSlot(slot.id, { owner: "myself" }), "Assigned to you", "Schedule the date next.")} disabled={isPending}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:brightness-110 disabled:opacity-50">
            <User size={11} /> Me
          </button>
          <button type="button" onClick={() => setMode("partner")} disabled={isPending}
            className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-[var(--color-edify-border)] text-[11px] font-bold hover:bg-[var(--color-edify-soft)]/40 disabled:opacity-50">
            <Handshake size={11} /> Partner
          </button>
        </>
      )}

      {/* Sub-steps (compact buttons) */}
      {mode === "none" && canSchedule && (
        <IconBtn onClick={() => setMode("schedule")} icon={<CalendarClock size={11} />} label={slot.scheduledFor ? "Reschedule" : "Schedule"} />
      )}
      {mode === "none" && canStart && (
        <IconBtn onClick={() => run(startCoreSlot(slot.id), "Activity started", "Now in progress.")} icon={<Play size={11} />} label="Start" tone="amber" disabled={isPending} />
      )}
      {mode === "none" && canUploadEvidence && (
        <IconBtn onClick={() => setMode("evidence")} icon={<Upload size={11} />} label="Evidence" />
      )}
      {mode === "none" && canReviewEvidence && (
        <>
          <IconBtn onClick={() => run(acceptCoreEvidence(slot.id), "Evidence accepted", "Staff can now enter the Salesforce ID.")} icon={<ClipboardCheck size={11} />} label="Accept" tone="teal" disabled={isPending} />
          <IconBtn onClick={() => setMode("evreturn")} icon={<RotateCcw size={11} />} label="Return" tone="rose" />
        </>
      )}
      {mode === "none" && canComplete && (
        <IconBtn onClick={() => setMode("complete")} icon={<CheckCircle2 size={11} />} label="Complete" tone="emerald" />
      )}

      {/* Inline forms */}
      {mode === "return" && (
        <InlineReason value={reason} setValue={setReason} onSend={() => run(returnCoreSlot(slot.id, reason), "Returned", "Sent back for correction.")} onCancel={() => setMode("none")} pending={isPending} tone="rose" />
      )}
      {mode === "evreturn" && (
        <InlineReason value={reason} setValue={setReason} onSend={() => run(returnCoreEvidence(slot.id, reason), "Evidence returned", "Partner asked to re-upload.")} onCancel={() => setMode("none")} pending={isPending} tone="rose" />
      )}
      {mode === "partner" && (
        <span className="inline-flex items-center gap-1.5">
          <input value={partnerName} onChange={(e) => setPartnerName(e.target.value)} list="core-partner-list" placeholder="Partner org" aria-label="Partner organisation"
            className="h-7 w-[150px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-violet-300" />
          <datalist id="core-partner-list">{listPartners().map((p) => <option key={p.id} value={p.name} />)}</datalist>
          <button type="button" disabled={isPending || partnerName.trim().length < 2}
            onClick={() => run(assignCoreSlot(slot.id, { owner: "partner", ownerName: partnerName.trim() }), "Assigned to partner", `${partnerName.trim()} has been notified.`)}
            className="h-7 px-2 rounded-md bg-violet-600 text-white text-[11px] font-bold disabled:opacity-50">Assign</button>
          <CancelBtn onClick={() => setMode("none")} />
        </span>
      )}
      {mode === "schedule" && (
        <span className="inline-flex items-center gap-1.5">
          <select value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" className="h-7 rounded-md border border-[var(--color-edify-border)] text-[11px] px-1">
            {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={week} onChange={(e) => setWeek(e.target.value)} aria-label="Week" className="h-7 rounded-md border border-[var(--color-edify-border)] text-[11px] px-1">
            {[1, 2, 3, 4].map((w) => <option key={w} value={w}>Wk {w}</option>)}
          </select>
          <button type="button" disabled={isPending} onClick={() => run(scheduleCoreSlot(slot.id, `${month} 2026`, Number(week)), "Scheduled", "Date set.")}
            className="h-7 px-2 rounded-md bg-sky-600 text-white text-[11px] font-bold disabled:opacity-50">Set</button>
          <CancelBtn onClick={() => setMode("none")} />
        </span>
      )}
      {mode === "evidence" && (
        <span className="inline-flex items-center gap-1.5">
          <input value={evidenceUri} onChange={(e) => setEvidenceUri(e.target.value)} placeholder="Evidence link / file ref" aria-label="Evidence URI"
            className="h-7 w-[170px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-amber-300" />
          <button type="button" disabled={isPending || evidenceUri.trim().length < 3} onClick={() => run(uploadCoreEvidence(slot.id, evidenceUri.trim()), "Evidence uploaded", isPartnerSlot ? "Awaiting reviewer acceptance." : "Now enter the Salesforce ID.")}
            className="h-7 px-2 rounded-md bg-amber-600 text-white text-[11px] font-bold disabled:opacity-50">Upload</button>
          <CancelBtn onClick={() => setMode("none")} />
        </span>
      )}
      {mode === "complete" && (
        <span className="inline-flex items-center gap-1.5 flex-wrap">
          <input value={sf} onChange={(e) => setSf(e.target.value)} placeholder={`${prefix}- Salesforce ID`} aria-label="Salesforce ID"
            className="h-7 w-[150px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-emerald-300" />
          {isTraining && (
            <>
              <input value={teachers} onChange={(e) => setTeachers(e.target.value)} type="number" min={0} placeholder="Teachers" aria-label="Teachers" className="h-7 w-[72px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2" />
              <input value={leaders} onChange={(e) => setLeaders(e.target.value)} type="number" min={0} placeholder="Leaders" aria-label="School leaders" className="h-7 w-[72px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2" />
            </>
          )}
          <button type="button" disabled={isPending || !completeReady}
            onClick={() => run(completeCoreSlot(slot.id, { salesforceId: sf.trim(), teachers: teachers ? Number(teachers) : undefined, leaders: leaders ? Number(leaders) : undefined }), "Submitted to IA", "Awaiting IA verification.")}
            className="h-7 px-2 rounded-md bg-emerald-600 text-white text-[11px] font-bold disabled:opacity-50">Submit</button>
          <CancelBtn onClick={() => setMode("none")} />
        </span>
      )}
    </div>
  );
}

const TONE_BTN: Record<string, string> = {
  default: "border border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
  amber: "bg-amber-500 text-white hover:bg-amber-600",
  teal: "bg-teal-600 text-white hover:bg-teal-700",
  rose: "border border-rose-200 text-rose-700 hover:bg-rose-50",
  emerald: "bg-emerald-600 text-white hover:bg-emerald-700",
};
function IconBtn({ onClick, icon, label, tone = "default", disabled }: { onClick: () => void; icon: React.ReactNode; label: string; tone?: keyof typeof TONE_BTN; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1 h-7 px-2 rounded-md text-[11px] font-bold disabled:opacity-50 ${TONE_BTN[tone]}`}>
      {icon} {label}
    </button>
  );
}
function CancelBtn({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-label="Cancel" className="w-6 h-7 grid place-items-center text-slate-500"><X size={12} /></button>;
}
function InlineReason({ value, setValue, onSend, onCancel, pending }: { value: string; setValue: (v: string) => void; onSend: () => void; onCancel: () => void; pending: boolean; tone?: "rose" }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Reason" aria-label="Reason"
        className="h-7 w-[140px] rounded-md border border-rose-200 text-[11px] px-2 focus:outline-none focus:ring-2 focus:ring-rose-300" />
      <button type="button" disabled={pending || value.trim().length < 5} onClick={onSend} className="h-7 px-2 rounded-md bg-rose-600 text-white text-[11px] font-bold disabled:opacity-50">Send</button>
      <CancelBtn onClick={onCancel} />
    </span>
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
