"use client";

// PartnerReviewActions — the Confirm / Return / Reject trio for any
// surface that needs to review a partner-completion claim (spec
// section 7–11).
//
// Three distinct affordances, not "Approve" + a "Reject" button.
// Return is for evidence/report problems; Reject is for "the work
// wasn't done" cases. The two flows emit different system messages
// and route to different reviewers.

import { useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  RotateCcw,
  Send,
  Stamp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { REJECT_REASONS, RETURN_REASONS, rejectReasonByKey } from "@/lib/partner-review/reasons";
import type { PartnerReviewOutcome, ReviewSubmission } from "@/lib/partner-review/types";

type Stage = "idle" | "return" | "reject";

export type ReviewSubmitInput = Omit<ReviewSubmission, "id" | "reviewerUserId" | "reviewerName" | "createdAt">;

export function PartnerReviewActions({
  activityId,
  activityLabel,
  schoolName,
  requireSchoolStamp = false,
  onSubmit,
}: {
  activityId:    string;
  activityLabel: string;
  schoolName:    string;
  /** Partner school visits: the visit form must carry the school stamp.
   *  Confirm stays blocked until the reviewer attests the stamp is
   *  present; no stamp ⇒ Return for Correction (spec section 6 + 9). */
  requireSchoolStamp?: boolean;
  onSubmit:      (input: ReviewSubmitInput) => Promise<void> | void;
}) {
  const [stage, setStage] = useState<Stage>("idle");
  const [submitting, setSubmitting] = useState(false);
  const [stampConfirmed, setStampConfirmed] = useState(false);

  // Return-flow state
  const [returnReasonKey, setReturnReasonKey] = useState("");
  const [returnComment, setReturnComment] = useState("");
  const [returnDueDate, setReturnDueDate] = useState("");

  // Reject-flow state
  const [rejectReasonKey, setRejectReasonKey] = useState("");
  const [rejectComment, setRejectComment] = useState("");
  const [rejectAction, setRejectAction] = useState("");

  async function fire(outcome: PartnerReviewOutcome, payload: Partial<ReviewSubmitInput>) {
    setSubmitting(true);
    try {
      await onSubmit({
        activityId,
        activityLabel,
        schoolName,
        outcome,
        ...payload,
      });
      // Reset after success.
      setStage("idle");
      setStampConfirmed(false);
      setReturnReasonKey(""); setReturnComment(""); setReturnDueDate("");
      setRejectReasonKey(""); setRejectComment(""); setRejectAction("");
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[partner-review] submit failed", err);
    } finally {
      setSubmitting(false);
    }
  }

  if (stage === "return") {
    const canSubmit = returnReasonKey.length > 0 && returnComment.trim().length > 0 && returnDueDate.trim().length > 0 && !submitting;
    return (
      <section className="card p-3.5 lg:p-5 border-amber-200 bg-amber-50/30">
        <BackHeader title="Return for correction" subtitle="Use when the work may be valid but the evidence or report needs fixing." Icon={RotateCcw} tone="amber" onBack={() => setStage("idle")} />
        <div className="mt-4 space-y-3">
          <ReasonSelect
            label="Correction reason"
            value={returnReasonKey}
            onChange={setReturnReasonKey}
            options={RETURN_REASONS.map((r) => ({ value: r.key, label: r.label }))}
          />
          <Textarea
            label="Reviewer comment"
            placeholder="What needs to change? Be specific — the partner reads this verbatim."
            value={returnComment}
            onChange={setReturnComment}
            required
          />
          <Input
            label="Due date"
            placeholder="e.g. Sat May 16"
            value={returnDueDate}
            onChange={setReturnDueDate}
            required
          />
        </div>
        <ActionFooter
          submitting={submitting}
          canSubmit={canSubmit}
          onSubmit={() =>
            fire("return", {
              reasonKey:       returnReasonKey,
              reviewerComment: returnComment.trim(),
              dueDate:         returnDueDate.trim(),
            })
          }
          submitLabel="Return for correction"
          tone="amber"
        />
      </section>
    );
  }

  if (stage === "reject") {
    const reason = rejectReasonByKey(rejectReasonKey);
    const notesRequired = reason?.requiresNotes ?? false;
    const canSubmit =
      rejectReasonKey.length > 0 &&
      rejectComment.trim().length > 0 &&
      rejectAction.trim().length > 0 &&
      (!notesRequired || rejectComment.trim().length > 0) &&
      !submitting;

    return (
      <section className="card p-3.5 lg:p-5 border-rose-200 bg-rose-50/30">
        <BackHeader title="Reject work" subtitle="Use when the claimed work was not done or doesn't qualify. The partner must redo the activity — payment stays blocked." Icon={Ban} tone="rose" onBack={() => setStage("idle")} />
        <div className="mt-4 space-y-3">
          <ReasonSelect
            label="Rejection reason"
            value={rejectReasonKey}
            onChange={setRejectReasonKey}
            options={REJECT_REASONS.map((r) => ({ value: r.key, label: r.label, severe: r.serious }))}
          />
          <Textarea
            label={notesRequired ? "Reviewer comment (required for 'Other')" : "Reviewer comment"}
            placeholder="What did the evidence show, and why doesn't it qualify?"
            value={rejectComment}
            onChange={setRejectComment}
            required
          />
          <Input
            label="Required next action"
            placeholder="e.g. Redo the assigned visit at Hope Primary and submit fresh evidence."
            value={rejectAction}
            onChange={setRejectAction}
            required
          />
          {reason?.serious && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-caption text-rose-800">
              <span className="font-extrabold">Serious rejection.</span> This category routes a copy to PL + CD with Urgent priority.
            </div>
          )}
        </div>
        <ActionFooter
          submitting={submitting}
          canSubmit={canSubmit}
          onSubmit={() =>
            fire("reject", {
              reasonKey:       rejectReasonKey,
              reviewerComment: rejectComment.trim(),
              requiredAction:  rejectAction.trim(),
            })
          }
          submitLabel="Reject work"
          tone="rose"
        />
      </section>
    );
  }

  // Idle — three buttons.
  const confirmBlockedByStamp = requireSchoolStamp && !stampConfirmed;
  return (
    <section className="card p-3.5 lg:p-5">
      <h3 className="text-body-lg font-extrabold tracking-tight">Review Work</h3>
      <p className="text-caption text-muted mt-0.5">
        Confirm if the work is complete and the evidence holds up. Return if the evidence needs fixing. Reject if the work wasn't actually done.
      </p>

      {requireSchoolStamp && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setStampConfirmed((v) => !v)}
            className={cn(
              "w-full flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
              stampConfirmed
                ? "border-emerald-300 bg-emerald-50/70"
                : "border-amber-300 bg-amber-50/40 hover:bg-amber-50",
            )}
          >
            <span className={cn(
              "h-5 w-5 rounded-md grid place-items-center shrink-0 border",
              stampConfirmed ? "bg-emerald-500 border-emerald-500 text-white" : "border-amber-400 bg-white text-amber-700",
            )}>
              {stampConfirmed ? <CheckCircle2 size={13} /> : <Stamp size={12} />}
            </span>
            <span className="text-caption leading-snug">
              <span className="font-extrabold">School stamp confirmed</span>
              <span className="text-muted"> — the school visit form carries the school stamp.</span>
            </span>
          </button>
          {confirmBlockedByStamp && (
            <p className="mt-1.5 text-[11px] text-amber-800 font-semibold inline-flex items-start gap-1">
              <AlertTriangle size={12} className="mt-[1px] shrink-0" />
              No school stamp = evidence incomplete. Confirm the stamp, or Return for Correction (reason: School stamp missing). Payment stays blocked.
            </p>
          )}
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2">
        <button
          type="button"
          disabled={submitting || confirmBlockedByStamp}
          onClick={() => fire("confirm", requireSchoolStamp ? { schoolStampConfirmed: true } : {})}
          className={cn(
            "h-10 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center justify-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)]",
            confirmBlockedByStamp
              ? "bg-[var(--color-edify-muted)] cursor-not-allowed"
              : "bg-emerald-600 hover:bg-emerald-500",
          )}
        >
          <CheckCircle2 size={14} />
          Confirm work complete
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => setStage("return")}
          className="h-10 px-4 rounded-lg border border-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-900 text-body font-extrabold inline-flex items-center justify-center gap-1.5"
        >
          <RotateCcw size={14} />
          Return for correction
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => setStage("reject")}
          className="h-10 px-4 rounded-lg border border-rose-300 bg-rose-50 hover:bg-rose-100 text-rose-800 text-body font-extrabold inline-flex items-center justify-center gap-1.5"
        >
          <Ban size={14} />
          Reject work
        </button>
      </div>
    </section>
  );
}

// ───────────────────────── sub-components ─────────────────────────

function BackHeader({
  title,
  subtitle,
  Icon,
  tone,
  onBack,
}: {
  title:    string;
  subtitle: string;
  Icon:     typeof RotateCcw;
  tone:     "amber" | "rose";
  onBack:   () => void;
}) {
  const iconCls = tone === "amber"
    ? "bg-amber-100 text-amber-800"
    : "bg-rose-100 text-rose-800";
  const titleCls = tone === "amber" ? "text-amber-900" : "text-rose-900";
  return (
    <header className="flex items-start gap-3">
      <button
        type="button"
        onClick={onBack}
        aria-label="Back to review actions"
        className="h-8 w-8 rounded-lg grid place-items-center hover:bg-white/60 text-muted shrink-0"
      >
        <ArrowLeft size={14} />
      </button>
      <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0", iconCls)}>
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <h3 className={cn("text-body-lg font-extrabold tracking-tight", titleCls)}>{title}</h3>
        <p className="text-caption text-muted mt-0.5 leading-snug">{subtitle}</p>
      </div>
    </header>
  );
}

function ReasonSelect({
  label,
  value,
  onChange,
  options,
}: {
  label:    string;
  value:    string;
  onChange: (v: string) => void;
  options:  { value: string; label: string; severe?: boolean }[];
}) {
  return (
    <label className="block">
      <span className="text-body font-extrabold tracking-tight">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1.5 h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
      >
        <option value="" disabled>Select a reason…</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}{o.severe ? "  ·  serious" : ""}</option>
        ))}
      </select>
    </label>
  );
}

function Input({
  label,
  placeholder,
  value,
  onChange,
  required,
}: {
  label:       string;
  placeholder: string;
  value:       string;
  onChange:    (v: string) => void;
  required?:   boolean;
}) {
  return (
    <label className="block">
      <span className="text-body font-extrabold tracking-tight">
        {label}
        {required && <span className="text-rose-700 ml-1">*</span>}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1.5 h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
      />
    </label>
  );
}

function Textarea({
  label,
  placeholder,
  value,
  onChange,
  required,
}: {
  label:       string;
  placeholder: string;
  value:       string;
  onChange:    (v: string) => void;
  required?:   boolean;
}) {
  return (
    <label className="block">
      <span className="text-body font-extrabold tracking-tight">
        {label}
        {required && <span className="text-rose-700 ml-1">*</span>}
      </span>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, 2000))}
        rows={3}
        placeholder={placeholder}
        className="mt-1.5 w-full px-3 py-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-y"
      />
    </label>
  );
}

function ActionFooter({
  submitting,
  canSubmit,
  onSubmit,
  submitLabel,
  tone,
}: {
  submitting:  boolean;
  canSubmit:   boolean;
  onSubmit:    () => void;
  submitLabel: string;
  tone:        "amber" | "rose";
}) {
  const enabledBg = tone === "amber"
    ? "bg-amber-600 hover:bg-amber-500"
    : "bg-rose-600 hover:bg-rose-500";
  return (
    <footer className="mt-4 pt-3 border-t border-[var(--color-edify-divider)] flex items-center justify-end gap-2">
      {!canSubmit && !submitting && (
        <span className="inline-flex items-center gap-1.5 text-caption font-semibold text-amber-700">
          <AlertTriangle size={12} />
          Fill in reason, comment, and the trailing field to submit.
        </span>
      )}
      <button
        type="button"
        disabled={!canSubmit}
        onClick={onSubmit}
        className={cn(
          "h-10 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)] transition-colors",
          canSubmit ? enabledBg : "bg-[var(--color-edify-muted)] cursor-not-allowed",
        )}
      >
        <Send size={13} />
        {submitting ? "Submitting…" : submitLabel}
      </button>
    </footer>
  );
}
