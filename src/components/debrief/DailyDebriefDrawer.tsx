"use client";

// Daily Field Debrief — a floating drawer (like the message / notification
// drawers) that submits to the backend. Not a local note: it persists, routes
// to PL/CD/IA/HR, and notifies. Slides in from the right on desktop, becomes a
// full-screen sheet on mobile, warns on unsaved close, submit pinned at bottom.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X, ClipboardList, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";

// The 18 official blocker reasons (spec §2D).
const BLOCKERS: { key: string; label: string }[] = [
  { key: "no_funds", label: "No funds" },
  { key: "funds_delayed", label: "Funds delayed" },
  { key: "transport_late", label: "Transport came late" },
  { key: "no_transport", label: "No transport" },
  { key: "public_holiday", label: "Public holiday" },
  { key: "leader_unavailable", label: "School leader not available" },
  { key: "school_closed", label: "School closed" },
  { key: "meeting_postponed", label: "Meeting postponed" },
  { key: "weather", label: "Weather issue" },
  { key: "sickness", label: "Sickness" },
  { key: "security", label: "Security issue" },
  { key: "partner_delay", label: "Partner delay" },
  { key: "evidence_missing", label: "Evidence missing" },
  { key: "salesforce_entry_issue", label: "Salesforce entry issue" },
  { key: "poor_attendance", label: "Poor attendance" },
  { key: "low_participation", label: "Low school participation" },
  { key: "data_collection_issue", label: "Data collection issue" },
  { key: "other", label: "Other" },
];

type Phase = "form" | "submitting" | "success" | "error";

export function DailyDebriefDrawer({
  open,
  onClose,
  onSubmitted,
  debriefType = "staff",
  partnerId,
}: {
  open: boolean;
  onClose: () => void;
  onSubmitted?: () => void;
  debriefType?: "staff" | "partner";
  partnerId?: string;
}) {
  const [mounted, setMounted] = useState(false);
  const [whatHappened, setWhatHappened] = useState("");
  const [whatWentWell, setWhatWentWell] = useState("");
  const [whatDidNotGoWell, setWhatDidNotGoWell] = useState("");
  const [blockers, setBlockers] = useState<string[]>([]);
  const [blockerOther, setBlockerOther] = useState("");
  const [supportNeeded, setSupportNeeded] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState<string | null>(null);
  // Spec §19: the drawer prefills from today's plan + proof queues so the
  // CCEO edits a draft instead of typing from memory. One attempt per
  // mount; non-CCEO sessions (403) skip silently.
  const [prefillTried, setPrefillTried] = useState(false);
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open || prefillTried || debriefType !== "staff") return;
    if (whatHappened || blockers.length) { setPrefillTried(true); return; }
    setPrefillTried(true);
    (async () => {
      try {
        const [planRes, queueRes] = await Promise.allSettled([
          fetch("/api/cceo/my-plan", { credentials: "include" }),
          fetch("/api/cceo/evidence-queue", { credentials: "include" }),
        ]);
        let summary = "";
        const suggested: string[] = [];
        if (planRes.status === "fulfilled" && planRes.value.ok) {
          const j = await planRes.value.json();
          const sections: { key: string; items: { typeLabel: string; entityName: string }[] }[] =
            j?.data?.sections ?? [];
          const line = (key: string, label: string) => {
            const items = sections.find((s) => s.key === key)?.items ?? [];
            if (!items.length) return "";
            const names = items.slice(0, 4).map((i) => `${i.typeLabel} — ${i.entityName}`).join("; ");
            return `${label}: ${names}${items.length > 4 ? ` (+${items.length - 4} more)` : ""}.\n`;
          };
          summary += line("dueToday", "Planned today");
          summary += line("needsAttention", "Rescheduled / carried over");
          summary += line("waitingOnMe", "Awaiting my evidence / Salesforce ID");
        }
        if (queueRes.status === "fulfilled" && queueRes.value.ok) {
          const j = await queueRes.value.json();
          const counts = j?.data?.counts;
          if (counts?.evidence > 0) suggested.push("evidence_missing");
          if (counts?.salesforce > 0) suggested.push("salesforce_entry_issue");
        }
        if (summary) { setWhatHappened(summary.trimEnd()); setPrefilled(true); }
        if (suggested.length) { setBlockers((b) => (b.length ? b : suggested)); setPrefilled(true); }
      } catch {
        /* prefill is best-effort — the form stays blank */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prefillTried, debriefType]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") attemptClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, whatHappened, whatWentWell, whatDidNotGoWell, blockers]);

  const dirty = !!(whatHappened || whatWentWell || whatDidNotGoWell || blockers.length || supportNeeded || nextAction);
  const canSubmit = whatHappened.trim().length > 3 && (!blockers.includes("other") || blockerOther.trim().length > 0);

  function attemptClose() {
    if (phase === "submitting") return;
    if (dirty && phase === "form" && !window.confirm("Discard this debrief? Your notes will be lost.")) return;
    reset();
    onClose();
  }
  function reset() {
    setWhatHappened(""); setWhatWentWell(""); setWhatDidNotGoWell(""); setBlockers([]); setBlockerOther("");
    setSupportNeeded(""); setNextAction(""); setPhase("form"); setError(null);
    setPrefillTried(false); setPrefilled(false);
  }
  const toggleBlocker = (k: string) => setBlockers((b) => (b.includes(k) ? b.filter((x) => x !== k) : [...b, k]));

  async function submit() {
    setPhase("submitting"); setError(null);
    try {
      const res = await fetch("/api/debriefs", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ debriefType, partnerId, whatHappened, whatWentWell, whatDidNotGoWell, blockers, blockerOther, supportNeeded, nextAction }),
      });
      const j = await res.json();
      if (j.live && j.id) { setPhase("success"); onSubmitted?.(); setTimeout(() => { reset(); onClose(); }, 1400); }
      else { setPhase("error"); setError(j.error || "Submission failed. The debrief was not saved."); }
    } catch { setPhase("error"); setError("Could not reach the server. Try again."); }
  }

  if (!mounted || !open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-3 sm:p-4" role="dialog" aria-label="Daily Field Debrief" aria-modal="true">
      <div className="absolute inset-0 bg-[rgba(15,23,32,0.32)] backdrop-blur-[2px]" onClick={attemptClose} />
      <div className="relative w-full max-w-[540px] max-h-[90vh] rounded-2xl bg-[var(--surface-1)] shadow-2xl flex flex-col overflow-hidden animate-[popIn_.16s_ease-out]">
        {/* Header */}
        <header className="flex items-start gap-3 px-4 py-3.5 border-b border-[var(--color-edify-divider)]">
          <span className="h-9 w-9 rounded-xl bg-emerald-50 text-emerald-700 grid place-items-center shrink-0"><ClipboardList size={17} /></span>
          <div className="flex-1 min-w-0">
            <h2 className="text-[15px] font-extrabold tracking-tight">Daily Field Debrief</h2>
            <p className="text-[11.5px] muted leading-snug">Capture today’s field reality, blockers, completed work, and lessons learned.</p>
          </div>
          <button onClick={attemptClose} className="muted hover:text-[var(--color-edify-text)] p-1"><X size={18} /></button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3.5 space-y-4">
          {phase === "success" ? (
            <div className="py-16 text-center">
              <CheckCircle2 size={40} className="mx-auto text-emerald-500 mb-3" />
              <p className="text-[14px] font-extrabold">Debrief submitted</p>
              <p className="text-[12px] muted mt-1">Routed to your supervisor, CD, IA, and HR.</p>
            </div>
          ) : (
            <>
              {prefilled && (
                <p className="text-[11px] font-semibold text-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] rounded-lg px-2.5 py-1.5 -mb-1">
                  Prefilled from today&rsquo;s plan and proof queues — edit before submitting.
                </p>
              )}
              <Field label="What happened today?" required>
                <textarea value={whatHappened} onChange={(e) => setWhatHappened(e.target.value)} rows={3} placeholder="Schools visited, trainings, cluster meetings, partner work reviewed…" className={ta} />
              </Field>
              <div className="grid grid-cols-1 gap-3">
                <Field label="What went well?"><textarea value={whatWentWell} onChange={(e) => setWhatWentWell(e.target.value)} rows={2} className={ta} /></Field>
                <Field label="What did not go well?"><textarea value={whatDidNotGoWell} onChange={(e) => setWhatDidNotGoWell(e.target.value)} rows={2} className={ta} /></Field>
              </div>

              <Field label="Blockers / reasons">
                <div className="grid grid-cols-2 gap-1.5">
                  {BLOCKERS.map((b) => (
                    <button key={b.key} type="button" onClick={() => toggleBlocker(b.key)}
                      className={cn("text-left text-[11.5px] font-semibold rounded-lg border px-2 py-1.5 transition-colors",
                        blockers.includes(b.key) ? "bg-rose-50 border-rose-300 text-rose-700" : "border-[var(--color-edify-border)] hover:bg-slate-50 text-slate-600")}>
                      {b.label}
                    </button>
                  ))}
                </div>
                {blockers.includes("other") && (
                  <input value={blockerOther} onChange={(e) => setBlockerOther(e.target.value)} placeholder="Explain ‘Other’ (required)" className={cn(inp, "mt-2")} />
                )}
              </Field>

              <Field label="Support you need"><input value={supportNeeded} onChange={(e) => setSupportNeeded(e.target.value)} className={inp} placeholder="What support do you need from your supervisor?" /></Field>
              <Field label="Tomorrow / next action"><input value={nextAction} onChange={(e) => setNextAction(e.target.value)} className={inp} placeholder="Next planned action or urgent follow-up" /></Field>

              {phase === "error" && (
                <p className="text-[12px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-2.5 py-2 inline-flex items-start gap-1.5"><AlertTriangle size={14} className="mt-px shrink-0" /> {error}</p>
              )}
            </>
          )}
        </div>

        {/* Footer — submit pinned at bottom */}
        {phase !== "success" && (
          <footer className="px-4 py-3 border-t border-[var(--color-edify-divider)]">
            <button onClick={submit} disabled={!canSubmit || phase === "submitting"}
              className={cn("w-full h-11 rounded-xl font-extrabold text-[13px] inline-flex items-center justify-center gap-2",
                canSubmit && phase !== "submitting" ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white" : "bg-slate-200 text-slate-400 cursor-not-allowed")}>
              {phase === "submitting" ? <><Loader2 size={15} className="animate-spin" /> Submitting…</> : phase === "error" ? "Retry submission" : "Submit debrief"}
            </button>
            {!canSubmit && <p className="text-[10.5px] muted text-center mt-1.5">“What happened today?” is required{blockers.includes("other") ? " · explain ‘Other’" : ""}.</p>}
          </footer>
        )}
      </div>
      <style>{`@keyframes popIn{from{transform:scale(.96);opacity:.4}to{transform:scale(1);opacity:1}}`}</style>
    </div>,
    document.body,
  );
}

const ta = "w-full rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 text-[12.5px] leading-snug focus:outline-none focus:ring-2 focus:ring-emerald-200 resize-none";
const inp = "w-full rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 h-9 text-[12.5px] focus:outline-none focus:ring-2 focus:ring-emerald-200";

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">{label}{required && <span className="text-rose-500"> *</span>}</label>
      {children}
    </div>
  );
}
