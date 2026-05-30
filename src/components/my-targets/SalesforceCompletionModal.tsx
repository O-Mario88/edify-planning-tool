"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  CheckCircle2,
  Database,
  MessageSquare,
  X,
} from "lucide-react";
import type { PlannedActivity, ActivityType } from "@/lib/cceo-my-targets-engine";
import type { VisitCompletion, SalesforceIdKind } from "@/lib/cceo-execution-store";
import { cn } from "@/lib/utils";
import { useDialogA11y } from "@/components/ui/useDialogA11y";

// SalesforceCompletionModal — single-purpose: capture the Salesforce ID
// the CCEO already logged in the Salesforce app, and mark the todo
// "Submitted for Verification."
//
// Activity → SF ID kind:
//   • Cluster Training / Cluster Meeting → Training ID (SF-TRN-XXXX)
//   • Everything else (school / partner / follow-up / SSA / special)
//     → Visit ID (SF-VST-XXXX)
//
// We don't duplicate Salesforce data entry. Photos, signatures,
// attendance, observations, and SSA scoring all live in the Salesforce
// app — that's the system of record. The dashboard simply tracks
// completion against that record via its ID.

const TRAINING_TYPES = new Set<ActivityType>(["Cluster Training", "Cluster Meeting"]);

function sfIdKindFor(activity: PlannedActivity): SalesforceIdKind {
  return TRAINING_TYPES.has(activity.activityType) ? "Training ID" : "Visit ID";
}

function sfIdPrefixFor(kind: SalesforceIdKind): string {
  return kind === "Training ID" ? "SF-TRN-" : "SF-VST-";
}

export function SalesforceCompletionModal({
  activity,
  open,
  onClose,
  onComplete,
}: {
  activity:   PlannedActivity;
  open:       boolean;
  onClose:    () => void;
  onComplete: (c: VisitCompletion) => void;
}) {
  const kind   = sfIdKindFor(activity);
  const prefix = sfIdPrefixFor(kind);

  const [sfId, setSfId] = useState("");
  const [note, setNote] = useState("");

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
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [open]);

  if (!open) return null;

  const trimmed = sfId.trim();
  // Permissive: any non-empty ID with at least 6 chars (covers free-form
  // org-specific formats). Prefix hint shown but not enforced.
  const canSubmit = trimmed.length >= 6;

  function submit() {
    if (!canSubmit) return;
    onComplete({
      schoolId:         activity.schoolId,
      activityId:       activity.id,
      completedAt:      new Date().toISOString().replace("T", " ").slice(0, 16),
      salesforceId:     trimmed,
      salesforceIdKind: kind,
      note:             note.trim(),
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
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl shadow-black/20 focus:outline-none"
      >
        {/* Header */}
        <header className="border-b border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-3">
          <span className="h-9 w-9 rounded-md bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
            <CheckCircle2 size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-caption muted font-bold uppercase tracking-wide">Complete activity</div>
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
            <span className="muted">All evidence (photos, signature, attendance, scores) lives there. Once Salesforce returns the {kind.toLowerCase()}, paste it here to flip the todo to <span className="font-extrabold text-[var(--color-edify-text)]">Submitted for Verification</span>.</span>
          </div>

          <label className="block">
            <span className="text-caption muted font-bold uppercase tracking-wide inline-flex items-center gap-1.5">
              <Database size={11} />
              {kind} from Salesforce
            </span>
            <input
              autoFocus
              aria-label={`${kind} from Salesforce`}
              value={sfId}
              onChange={(e) => setSfId(e.target.value)}
              placeholder={`${prefix}…`}
              className="mt-1 w-full h-11 rounded-xl border border-[var(--color-edify-border)] bg-white px-3 text-body-lg font-mono font-extrabold tracking-tight focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <div className="text-[10px] muted mt-1">
              Expected format: <span className="font-mono font-extrabold">{prefix}XXXX</span>. Free-form accepted if your org uses a different convention.
            </div>
          </label>

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
              placeholder="Anything the Program Lead should know about the visit / training?"
              className="mt-1 w-full rounded-xl border border-[var(--color-edify-border)] bg-white p-3 text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>
        </div>

        <footer className="border-t border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-2 flex-wrap">
          <div className="text-caption muted flex-1 min-w-0">
            Status will flip to <span className="font-extrabold text-[var(--color-edify-text)]">Submitted for Verification</span>; Impact Assessment validates the Salesforce record.
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
                ? "bg-emerald-500 hover:bg-emerald-600 text-white shadow-sm shadow-emerald-500/25"
                : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            <CheckCircle2 size={13} />
            Submit completion
          </button>
        </footer>
      </div>
    </div>
  );
}
