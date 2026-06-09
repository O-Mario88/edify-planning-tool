"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  CheckCircle2,
  Database,
  MessageSquare,
  Users,
  ClipboardCheck,
  AlertCircle,
  X,
} from "lucide-react";
import type { VisitCompletion } from "@/lib/cceo-execution-store";
import {
  salesforceKindFor,
  kindLabel,
  requiresParticipantCounts,
  validateSalesforceId,
  SF_PREFIX,
  SF_EXAMPLE,
} from "@/lib/salesforce-id";
import { cn } from "@/lib/utils";
import { useDialogA11y } from "@/components/ui/useDialogA11y";

// SalesforceCompletionModal — the Salesforce Completion Verification Gate.
//
// Core rule: an activity is not complete until the required Salesforce
// Activity ID is entered and submitted. Evidence proves the work happened;
// the Salesforce ID proves it was entered into Salesforce.
//
// Two shapes, driven by the activity type:
//   • Complete Visit    → SV- Visit ID only (+ optional note)
//   • Complete Training → TS- Training ID + participant breakdown
//                         (teachers / school leaders / other) + attendance
//
// Cluster meetings are logged in Salesforce as trainings, so they use the
// training shape (TS- + participants + attendance).
//
// We don't duplicate Salesforce data entry. Photos, signatures, attendance,
// observations, and SSA scoring all live in the Salesforce app — that's the
// system of record. The dashboard tracks completion against that record via
// its ID, then sends it down the verification chain.

// Minimal activity descriptor — decoupled from any one engine type so
// the modal can be mounted from the CCEO targets view, the mobile plan,
// or any other completion surface.
export type CompletionActivity = {
  id:            string;
  schoolId?:     string;
  schoolName:    string;
  activityType:  string;   // label, e.g. "Follow-Up Visit" / "Cluster Training"
  purpose?:      string;
  intervention?: string;
};

export function SalesforceCompletionModal({
  activity,
  open,
  onClose,
  onComplete,
}: {
  activity:   CompletionActivity;
  open:       boolean;
  onClose:    () => void;
  onComplete: (c: VisitCompletion) => void;
}) {
  const kind      = salesforceKindFor(activity.activityType);
  const isTraining = requiresParticipantCounts(activity.activityType);
  const label     = kindLabel(kind);
  const prefix    = SF_PREFIX[kind];
  const example   = SF_EXAMPLE[kind];
  const title     = isTraining ? "Complete Training" : "Complete Visit";

  const [sfId, setSfId]   = useState("");
  const [note, setNote]   = useState("");
  const [teachers, setTeachers]           = useState("");
  const [schoolLeaders, setSchoolLeaders] = useState("");
  const [other, setOther]                 = useState("");
  const [attendance, setAttendance]       = useState(false);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  useDialogA11y({ open, onClose, containerRef: dialogRef });

  useEffect(() => {
    if (!open) return;
    // Reset form state every time the modal re-opens. Migrate to a
    // `key`-prop remount on the parent during the React-19 sweep.
    /* eslint-disable react-hooks/set-state-in-effect */
    setSfId("");
    setNote("");
    setTeachers("");
    setSchoolLeaders("");
    setOther("");
    setAttendance(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [open]);

  const trimmed = sfId.trim();
  const validation = validateSalesforceId(trimmed, kind);
  // Only surface the prefix error once the user has typed something that
  // isn't a valid prefix — no shouting at an empty field.
  const showSfError = trimmed.length > 0 && !validation.ok;

  const teachersN      = toCount(teachers);
  const schoolLeadersN = toCount(schoolLeaders);
  const otherN         = toCount(other);
  const total          = teachersN + schoolLeadersN + otherN;

  // Training gate: valid TS- ID + teachers + school leaders entered +
  // attendance confirmed + a non-zero total.
  // Visit gate: valid SV- ID.
  const participantsOk = teachers.trim() !== "" && schoolLeaders.trim() !== "" && total > 0;
  const canSubmit = isTraining
    ? validation.ok && participantsOk && attendance
    : validation.ok;

  if (!open) return null;

  function submit() {
    if (!canSubmit) return;
    const now = new Date().toISOString();
    onComplete({
      schoolId:         activity.schoolId ?? "",
      activityId:       activity.id,
      completedAt:      now.replace("T", " ").slice(0, 16),
      salesforceId:     trimmed,
      salesforceIdKind: label,
      note:             note.trim(),
      submittedAt:      now,
      ...(isTraining
        ? {
            participants: {
              teachers:      teachersN,
              schoolLeaders: schoolLeadersN,
              other:         otherN,
              total,
            },
            attendanceConfirmed: attendance,
          }
        : {}),
    });
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl shadow-black/20 focus:outline-none max-h-[92vh] overflow-y-auto"
      >
        {/* Header */}
        <header className="border-b border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-3 sticky top-0 bg-white rounded-t-2xl z-10">
          <span className="h-9 w-9 rounded-md bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
            <CheckCircle2 size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-caption muted font-bold uppercase tracking-wide">{title}</div>
            <h2 id={titleId} className="text-[15px] font-extrabold tracking-tight truncate">{activity.schoolName}</h2>
            <div className="text-caption muted truncate">
              {activity.activityType} · {activity.purpose}
              {activity.intervention ? ` · ${activity.intervention}` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="h-9 w-9 rounded-md hover:bg-[var(--color-edify-soft)]/40 grid place-items-center"
          >
            <X size={16} />
          </button>
        </header>

        <div className="p-4 space-y-3">
          <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-3 text-[11.5px] leading-snug">
            <span className="font-extrabold text-[var(--color-edify-text)]">Log the activity in the Salesforce app first.</span>{" "}
            <span className="muted">All evidence (photos, signature, attendance, scores) lives there. Once Salesforce returns the {label.toLowerCase()}, enter it here to flip the activity to <span className="font-extrabold text-[var(--color-edify-text)]">Submitted for Verification</span>.</span>
          </div>

          {/* Salesforce ID */}
          <label className="block">
            <span className="text-caption muted font-bold uppercase tracking-wide inline-flex items-center gap-1.5">
              <Database size={11} />
              Salesforce {label}
            </span>
            <input
              autoFocus
              aria-label={`Salesforce ${label}`}
              aria-invalid={showSfError}
              value={sfId}
              onChange={(e) => setSfId(e.target.value)}
              placeholder="Enter the SF ID here"
              className={cn(
                "mt-1 w-full h-11 rounded-xl border bg-white px-3 text-body-lg font-mono font-extrabold tracking-tight focus:outline-none focus:ring-2",
                showSfError
                  ? "border-rose-300 focus:ring-rose-400/30"
                  : "border-[var(--color-edify-border)] focus:ring-[var(--color-edify-primary)]/30",
              )}
            />
            {showSfError ? (
              <div className="text-[10.5px] text-rose-700 font-semibold mt-1 inline-flex items-start gap-1">
                <AlertCircle size={11} className="mt-[1px] shrink-0" />
                {validation.message}
              </div>
            ) : (
              <div className="text-[10px] muted mt-1">
                {isTraining ? "Training" : "School visit"} IDs must start with{" "}
                <span className="font-mono font-extrabold">{prefix}</span>, for example{" "}
                <span className="font-mono font-extrabold">{example}</span>.
              </div>
            )}
          </label>

          {/* Training-only: participant breakdown + attendance */}
          {isTraining && (
            <>
              <fieldset className="rounded-xl border border-[var(--color-edify-border)] p-3 space-y-2.5">
                <legend className="text-caption muted font-bold uppercase tracking-wide inline-flex items-center gap-1.5 px-1">
                  <Users size={11} />
                  Participants
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  <CountField label="Teachers trained" value={teachers} onChange={setTeachers} required />
                  <CountField label="School leaders" value={schoolLeaders} onChange={setSchoolLeaders} required />
                  <CountField label="Other (optional)" value={other} onChange={setOther} />
                  <div className="rounded-xl bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] px-3 py-2 flex flex-col justify-center">
                    <span className="text-[10px] muted font-bold uppercase tracking-wide">Total participants</span>
                    <span className="text-body-lg font-extrabold tabular tracking-tight">{total}</span>
                  </div>
                </div>
              </fieldset>

              <button
                type="button"
                onClick={() => setAttendance((v) => !v)}
                className={cn(
                  "w-full flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors",
                  attendance
                    ? "border-emerald-300 bg-emerald-50/70"
                    : "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/30",
                )}
              >
                <span className={cn(
                  "h-5 w-5 rounded-md grid place-items-center shrink-0 border",
                  attendance ? "bg-emerald-500 border-emerald-500 text-white" : "border-[var(--color-edify-border)] bg-white",
                )}>
                  {attendance && <ClipboardCheck size={13} />}
                </span>
                <span className="text-[12px] leading-snug">
                  <span className="font-extrabold">Attendance form received</span>
                  <span className="muted"> — uploaded to Salesforce / confirmed received from coordinators.</span>
                </span>
              </button>
            </>
          )}

          {/* Optional note */}
          <label className="block">
            <span className="text-caption muted font-bold uppercase tracking-wide inline-flex items-center gap-1.5">
              <MessageSquare size={11} />
              Completion note (optional)
            </span>
            <textarea
              aria-label="Completion note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder={isTraining ? "Anything the verifier should know about the training?" : "Anything the Program Lead should know about the visit?"}
              className="mt-1 w-full rounded-xl border border-[var(--color-edify-border)] bg-white p-3 text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>
        </div>

        <footer className="border-t border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-2 flex-wrap sticky bottom-0 bg-white rounded-b-2xl">
          <div className="text-caption muted flex-1 min-w-0">
            Status flips to <span className="font-extrabold text-[var(--color-edify-text)]">Submitted for Verification</span>; Impact Assessment validates the Salesforce record.
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-extrabold"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={submit}
            className={cn(
              "h-10 px-4 rounded-xl text-body font-extrabold inline-flex items-center gap-1.5",
              canSubmit
                ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-sm shadow-emerald-500/25"
                : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            <CheckCircle2 size={13} />
            Confirm
          </button>
        </footer>
      </div>
    </div>
  );
}

// ────────── sub-components ──────────

function CountField({
  label,
  value,
  onChange,
  required,
}: {
  label:    string;
  value:    string;
  onChange: (v: string) => void;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-[10px] muted font-bold uppercase tracking-wide">
        {label}
        {required && <span className="text-rose-600 ml-0.5">*</span>}
      </span>
      <input
        type="number"
        inputMode="numeric"
        min={0}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0"
        className="mt-1 w-full h-10 rounded-xl border border-[var(--color-edify-border)] bg-white px-3 text-body font-extrabold tabular focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
      />
    </label>
  );
}

function toCount(raw: string): number {
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}
