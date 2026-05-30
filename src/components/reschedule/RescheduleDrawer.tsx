"use client";

// RescheduleDrawer — modal/drawer for rescheduling any activity.
//
// Spec section 2: reason is REQUIRED, Submit stays disabled until at
// least one reason is checked. "Other" forces the notes field to
// become required. Reasons are grouped by category for fast scan.
//
// Submit calls a server action that:
//   1. Persists the RescheduleSubmission
//   2. Emits a system message to the routed reviewers
//   3. Returns or redirects
//
// Today the persistence is mock; the system message emit is real
// (writes to messages-v2). The route swap is one line in Phase 4.

import { useMemo, useState } from "react";
import { AlertTriangle, Calendar, CheckCircle2, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { CATEGORY_LABEL, CATEGORY_ORDER, RESCHEDULE_REASONS, reasonByKey } from "@/lib/reschedule/reasons";
import { ROLE_CHIP_LABEL, reviewerPlan } from "@/lib/reschedule/routing";
import type { RescheduleActor, ReschedulableActivity } from "@/lib/reschedule/types";

export type RescheduleSubmitInput = {
  activityId:    string;
  activityType:  ReschedulableActivity;
  activityLabel: string;
  schoolName?:   string;
  originalDate:  string;
  newDate:       string;
  reasonKeys:    string[];
  notes?:        string;
};

export function RescheduleDrawer({
  open,
  onClose,
  activityId,
  activityType,
  activityLabel,
  schoolName,
  originalDate,
  actor,
  /** Server action — receives the submission payload and emits the
   *  system message. Returns void on success (the host can listen on
   *  the close callback). */
  onSubmit,
}: {
  open:          boolean;
  onClose:       () => void;
  activityId:    string;
  activityType:  ReschedulableActivity;
  activityLabel: string;
  schoolName?:   string;
  originalDate:  string;
  actor:         RescheduleActor;
  onSubmit:      (input: RescheduleSubmitInput) => Promise<void> | void;
}) {
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState("");
  const [newDate, setNewDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const otherSelected = useMemo(
    () => [...selectedKeys].some((k) => reasonByKey(k)?.requiresNotes),
    [selectedKeys],
  );
  const notesRequired = otherSelected;
  const canSubmit =
    selectedKeys.size > 0 &&
    newDate.trim().length > 0 &&
    (!notesRequired || notes.trim().length > 0) &&
    !submitting;

  const plan = useMemo(() => reviewerPlan(actor), [actor]);

  function toggle(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onSubmit({
        activityId,
        activityType,
        activityLabel,
        schoolName,
        originalDate,
        newDate,
        reasonKeys: [...selectedKeys],
        notes: notes.trim() || undefined,
      });
      onClose();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[reschedule] submit failed", err);
      setSubmitting(false);
    }
  }

  if (!open) return null;

  const blockingMessage =
    selectedKeys.size === 0     ? "Select at least one reason." :
    newDate.trim().length === 0 ? "Pick a new date." :
    notesRequired && notes.trim().length === 0 ? "Add an explanation for the 'Other' reason." :
    null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reschedule-title"
      className="fixed inset-0 z-50 flex items-end lg:items-center justify-center bg-black/45 backdrop-blur-sm p-0 lg:p-6"
      onClick={onClose}
    >
      <form
        onSubmit={handleSubmit}
        onClick={(e) => e.stopPropagation()}
        className="bg-[var(--color-page)] w-full lg:w-[680px] max-h-[95vh] rounded-t-2xl lg:rounded-2xl shadow-2xl flex flex-col overflow-hidden"
      >
        <header className="flex items-start justify-between gap-3 px-5 lg:px-6 pt-5 pb-3 border-b border-[var(--color-edify-divider)]">
          <div className="min-w-0">
            <h2 id="reschedule-title" className="text-[16px] lg:text-[18px] font-extrabold tracking-tight">
              Reschedule activity
            </h2>
            <p className="text-caption text-muted mt-1 leading-snug max-w-[520px]">
              Pick why this activity is being rescheduled. The reason is shared with the right reviewers so blockers get unblocked.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="grid place-items-center h-9 w-9 rounded-lg hover:bg-[var(--color-edify-soft)]/40 text-muted"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 lg:px-6 py-4 space-y-4">
          {/* Current activity + dates */}
          <section className="card p-3.5 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <div className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted">Activity</div>
              <div className="text-body-lg font-extrabold mt-1 tracking-tight truncate">{activityLabel}</div>
              {schoolName && <div className="text-caption text-muted mt-0.5">{schoolName}</div>}
            </div>
            <div>
              <div className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted">Current date</div>
              <div className="text-body-lg font-extrabold mt-1 tracking-tight">{originalDate}</div>
            </div>
            <div className="sm:col-span-2">
              <label className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted inline-flex items-center gap-1.5">
                <Calendar size={11} />
                New date / week
              </label>
              <input
                type="text"
                value={newDate}
                onChange={(e) => setNewDate(e.target.value)}
                placeholder="e.g. June Week 3 / 18 June 2027"
                className="mt-1 h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
              />
            </div>
          </section>

          {/* Reasons */}
          <section className="card p-3.5">
            <div className="flex items-baseline justify-between gap-3 flex-wrap">
              <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                Reason(s) for rescheduling
                <span className="text-tiny font-extrabold uppercase tracking-[0.06em] bg-rose-50 text-rose-700 border border-rose-200 px-1.5 py-[1px] rounded-md">Required</span>
              </h3>
              {selectedKeys.size > 0 && (
                <span className="text-caption text-muted">{selectedKeys.size} selected</span>
              )}
            </div>
            <p className="text-caption text-muted mt-0.5">Pick all that apply. Routing depends on what's selected.</p>

            <div className="mt-4 space-y-4">
              {CATEGORY_ORDER.map((cat) => {
                const reasons = RESCHEDULE_REASONS.filter((r) => r.category === cat);
                if (reasons.length === 0) return null;
                return (
                  <div key={cat}>
                    <div className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted mb-2">
                      {CATEGORY_LABEL[cat]}
                    </div>
                    <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                      {reasons.map((r) => {
                        const active = selectedKeys.has(r.key);
                        return (
                          <li key={r.key}>
                            <button
                              type="button"
                              onClick={() => toggle(r.key)}
                              className={cn(
                                "w-full text-left h-9 px-3 rounded-lg border text-body inline-flex items-center gap-2 transition-colors",
                                active
                                  ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                                  : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
                              )}
                            >
                              {active && <CheckCircle2 size={12} />}
                              <span className="truncate">{r.label}</span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Notes */}
          <section className="card p-3.5">
            <label className="block">
              <span className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                Additional notes
                {notesRequired && (
                  <span className="text-tiny font-extrabold uppercase tracking-[0.06em] bg-rose-50 text-rose-700 border border-rose-200 px-1.5 py-[1px] rounded-md">Required for "Other"</span>
                )}
              </span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value.slice(0, 1000))}
                rows={3}
                placeholder={notesRequired ? "Please explain the reason." : "Optional context for the reviewers."}
                className="mt-2 w-full px-3 py-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-y"
              />
              <span className="text-tiny text-muted tabular block text-right mt-0.5">{notes.length}/1000</span>
            </label>
          </section>

          {/* Routing preview */}
          <section className="card p-3.5">
            <div className="text-body-lg font-extrabold tracking-tight">Who will be notified</div>
            <p className="text-caption text-muted mt-0.5 leading-snug">
              {actor === "staff"
                ? "Because this is a staff activity, this reschedule reason will be sent to PL, IA, Accountant, and HR — HR uses these signals for staff support, workload patterns, and field reality."
                : "Because this is a partner activity, this reschedule reason will be sent to CCEO, PL, CD, IA, Accountant, and RVP — leadership tracks partner reliability and program risk at the regional level."}
            </p>
            <div className="mt-3 flex items-center gap-1.5 flex-wrap">
              {plan.roles.map((r) => (
                <span
                  key={r}
                  className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--color-edify-soft)]/70 border border-[var(--color-edify-border)] text-caption font-semibold"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  {ROLE_CHIP_LABEL[r]}
                </span>
              ))}
            </div>
          </section>
        </div>

        <footer className="px-5 lg:px-6 py-3 border-t border-[var(--color-edify-divider)] flex items-center justify-between gap-3 flex-wrap">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-semibold hover:bg-[var(--color-edify-soft)]/40"
          >
            Cancel
          </button>
          <div className="flex items-center gap-3 flex-wrap">
            {blockingMessage && (
              <span className="inline-flex items-center gap-1.5 text-caption font-semibold text-amber-700">
                <AlertTriangle size={12} />
                {blockingMessage}
              </span>
            )}
            <button
              type="submit"
              disabled={!canSubmit}
              className={cn(
                "h-9 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)] transition-colors",
                canSubmit
                  ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]"
                  : "bg-[var(--color-edify-muted)] cursor-not-allowed",
              )}
            >
              <Send size={13} />
              {submitting ? "Submitting…" : "Submit reschedule"}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}
