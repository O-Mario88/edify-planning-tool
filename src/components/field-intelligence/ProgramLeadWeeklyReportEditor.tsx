"use client";

import { useState } from "react";
import {
  FileText,
  Send,
  CheckCircle2,
  AlertTriangle,
  Lock,
  type LucideIcon,
} from "lucide-react";
import type {
  ProgramLeadWeeklyFieldReport,
  WeeklyReportStatus,
} from "@/lib/field-intelligence-mock";
import { canTransitionReport } from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

// PL editor for the weekly report narrative + decisions list.
// Status transitions: Generated → PL Editing → Submitted to CD.
// Once submitted, the form locks. Resubmit path opens only when CD has
// returned the report for clarification.

const STATUS_TONE: Record<WeeklyReportStatus, string> = {
  "Generated":                  "bg-slate-100   text-slate-700",
  "PL Editing":                 "bg-amber-100   text-amber-700",
  "Submitted to CD":            "bg-emerald-100 text-emerald-700",
  "Returned for Clarification": "bg-rose-100    text-rose-700",
  "Resubmitted":                "bg-violet-100  text-violet-700",
  "Reviewed by CD":             "bg-sky-100     text-sky-700",
  "Closed":                     "bg-slate-100   text-slate-500",
};

export function ProgramLeadWeeklyReportEditor({ r }: { r: ProgramLeadWeeklyFieldReport }) {
  const [status, setStatus] = useState<WeeklyReportStatus>(r.status);
  const [narrative, setNarrative] = useState(r.programLeadWeeklyDebrief);
  const [decisions, setDecisions] = useState<string[]>(r.decisionsRequiredFromCD);
  const [draftDecision, setDraftDecision] = useState("");

  const locked = status === "Submitted to CD" || status === "Reviewed by CD" || status === "Closed";
  const canSubmit  = (status === "Generated" || status === "PL Editing") && canTransitionReport(status, "Submitted to CD");
  const canResubmit = status === "Returned for Clarification" && canTransitionReport(status, "Resubmitted");

  function attempt(next: WeeklyReportStatus) {
    if (!canTransitionReport(status, next)) return;
    setStatus(next);
  }

  return (
    <div className="space-y-4">
      <header className="card p-3.5 space-y-3">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="text-[11px] muted font-bold uppercase tracking-wider">Program Lead · Weekly Field Report Editor</div>
            <h1 className="text-[22px] sm:text-[26px] font-extrabold tracking-tight mt-0.5">{r.programLeadName}</h1>
            <div className="text-body muted mt-0.5">
              {r.team} · {r.region} · {r.weekLabel}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold whitespace-nowrap", STATUS_TONE[status])}>
              {status}
            </span>
            {locked && (
              <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold bg-slate-100 text-slate-600">
                <Lock size={10} />
                Locked
              </span>
            )}
          </div>
        </div>
        <p className="text-[11.5px] muted leading-snug">
          The system auto-fills your activity numbers, debrief submission rate, and barriers from your team&apos;s daily debriefs.
          You only edit your own weekly reflection and the decisions list — then submit to the Country Director.
        </p>
      </header>

      {/* Auto-filled summary (read-only) */}
      <section className="card p-3.5 space-y-3">
        <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
          <FileText size={14} className="text-[var(--color-edify-primary)]" />
          Auto-filled by the system
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
          <Stat label="Planned"          value={r.totalPlannedActivities} />
          <Stat label="Completed"        value={r.totalCompletedActivities} tone="green" />
          <Stat label="Verified"         value={r.totalVerifiedActivities}  tone="green" />
          <Stat label="Salesforce pending" value={r.salesforcePendingCount} tone="amber" />
          <Stat label="Submission rate" value={`${r.debriefSubmissionRate}%`} tone={r.debriefSubmissionRate >= 90 ? "green" : "amber"} />
          <Stat label="Raw / Adjusted"  value={`${r.rawAchievementPercent}% / ${r.contextAdjustedAchievementPercent}%`} />
        </div>
        <p className="text-caption muted leading-snug">
          Top barriers (auto): {r.topBarriers.map((b) => b.category).join(" · ") || "—"}.
          Numbers can&apos;t be edited here — fix at the daily debrief level if anything looks wrong.
        </p>
      </section>

      {/* Editable narrative */}
      <section className="card p-3.5 space-y-3">
        <h2 className="text-body-lg font-extrabold tracking-tight">Your weekly reflection</h2>
        <NarrativeField label="What went well with the team this week?"
          value={narrative.whatWentWell}
          onChange={(v) => setNarrative({ ...narrative, whatWentWell: v })}
          disabled={locked} />
        <NarrativeField label="What did not go well?"
          value={narrative.whatDidNotGoWell}
          onChange={(v) => setNarrative({ ...narrative, whatDidNotGoWell: v })}
          disabled={locked} />
        <NarrativeField label="Team support you provided"
          value={narrative.teamSupportProvided}
          onChange={(v) => setNarrative({ ...narrative, teamSupportProvided: v })}
          disabled={locked} />
        <NarrativeField label="Decisions you need from the Country Director (high-level — list specifics below)"
          value={narrative.decisionsNeededFromCD}
          onChange={(v) => setNarrative({ ...narrative, decisionsNeededFromCD: v })}
          disabled={locked} />
        <NarrativeField label="Next week priorities"
          value={narrative.nextWeekPriorities}
          onChange={(v) => setNarrative({ ...narrative, nextWeekPriorities: v })}
          disabled={locked} />
      </section>

      {/* Decisions list */}
      <section className="card p-3.5 space-y-3">
        <h2 className="text-body-lg font-extrabold tracking-tight">Decisions required from the Country Director</h2>
        <ul className="space-y-1.5">
          {decisions.map((d, i) => (
            <li key={i} className="flex items-start gap-2">
              <div className="rounded-md bg-rose-50 border border-rose-200 px-2 py-1 text-[10px] font-extrabold text-rose-700">{i + 1}</div>
              <div className="flex-1 text-body leading-snug">{d}</div>
              {!locked && (
                <button
                  type="button"
                  onClick={() => setDecisions((arr) => arr.filter((_, idx) => idx !== i))}
                  className="text-caption font-extrabold text-rose-700 hover:underline"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        {!locked && (
          <div className="flex items-center gap-2">
            <input
              aria-label="New decision required from CD"
              value={draftDecision}
              onChange={(e) => setDraftDecision(e.target.value)}
              placeholder="Add a specific decision the CD must make…"
              className="flex-1 h-9 rounded-xl border border-[var(--color-edify-border)] bg-white px-3 text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <button
              type="button"
              onClick={() => { if (draftDecision.trim()) { setDecisions((arr) => [...arr, draftDecision.trim()]); setDraftDecision(""); } }}
              disabled={!draftDecision.trim()}
              className={cn(
                "h-9 px-3 rounded-xl text-[12px] font-extrabold",
                draftDecision.trim()
                  ? "bg-[var(--color-edify-primary)] text-white hover:brightness-110"
                  : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
              )}
            >
              Add
            </button>
          </div>
        )}
      </section>

      {/* Submit lifecycle */}
      <section className="card p-3.5 flex items-center gap-3 flex-wrap">
        {locked ? (
          <>
            <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
            <div className="text-body leading-snug">
              <span className="font-extrabold">Report submitted.</span>
              <span className="muted"> The CD now sees it in the report center; you&apos;ll be notified if a clarification is requested.</span>
            </div>
          </>
        ) : status === "Returned for Clarification" ? (
          <>
            <AlertTriangle size={16} className="text-rose-700 shrink-0" />
            <div className="flex-1 text-body leading-snug">
              <span className="font-extrabold text-rose-800">Returned for clarification.</span>
              <span className="muted"> Address the CD&apos;s note above, then resubmit.</span>
            </div>
            <button
              type="button"
              onClick={() => attempt("Resubmitted")}
              disabled={!canResubmit}
              className="h-10 px-4 rounded-xl bg-[var(--color-edify-primary)] text-white text-[13px] font-extrabold inline-flex items-center gap-1.5 hover:brightness-110"
            >
              <Send size={13} />
              Resubmit to CD
            </button>
          </>
        ) : (
          <>
            <FileText size={16} className="text-[var(--color-edify-primary)] shrink-0" />
            <div className="flex-1 text-body leading-snug">
              <span className="font-extrabold">Ready to submit?</span>
              <span className="muted"> The narrative + decisions will be locked once submitted. The CD can return it for clarification if anything needs more detail.</span>
            </div>
            <button
              type="button"
              onClick={() => attempt("Submitted to CD")}
              disabled={!canSubmit}
              className={cn(
                "h-10 px-4 rounded-xl text-[13px] font-extrabold inline-flex items-center gap-1.5",
                canSubmit
                  ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-sm shadow-emerald-500/25"
                  : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
              )}
            >
              <Send size={13} />
              Submit to CD
            </button>
          </>
        )}
      </section>
    </div>
  );
}

// ────────── Pieces ──────────

function NarrativeField({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="block">
      <span className="text-caption muted font-bold uppercase tracking-wide">{label}</span>
      <textarea
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={3}
        className={cn(
          "mt-1 w-full rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2 text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30",
          disabled && "bg-[var(--color-edify-soft)]/30 text-[var(--color-edify-muted)]",
        )}
      />
    </label>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "edify" | "green" | "amber" }) {
  const tones = {
    edify: "bg-[var(--color-edify-soft)]/40 border-[var(--color-edify-border)]",
    green: "bg-emerald-50 border-emerald-200",
    amber: "bg-amber-50 border-amber-200",
  } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2", tones[tone ?? "edify"])}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
      <div className="text-[16px] font-extrabold tabular leading-tight">{value}</div>
    </div>
  );
}

// Silence unused-icon warnings for icons we keep around for the lifecycle UI.
void (null as unknown as LucideIcon);
