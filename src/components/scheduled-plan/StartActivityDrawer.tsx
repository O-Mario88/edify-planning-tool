"use client";

// StartActivityDrawer — confirmation modal for Start Activity.
//
// Spec §7: show the activity, purpose, owner, scheduled date, and
// the required evidence list, then ask Cancel / Start Now. When the
// user confirms, the server action transitions status to In Progress
// and the card flips to show Complete Activity instead.

import { useState } from "react";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ClipboardList,
  Play,
  Target,
  Users,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ScheduledPlan } from "@/lib/scheduled-plan/types";

export function StartActivityDrawer({
  open,
  onClose,
  plan,
  /** Server action — receives activityId in FormData, transitions
   *  status to In Progress, revalidates the calling surface. */
  startAction,
}: {
  open:        boolean;
  onClose:     () => void;
  plan:        ScheduledPlan;
  startAction: (formData: FormData) => Promise<void> | void;
}) {
  const [submitting, setSubmitting] = useState(false);

  async function handleStart() {
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("activityId", plan.id);
      fd.append("activityLabel", plan.label);
      await startAction(fd);
      onClose();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[start-activity] failed", err);
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="start-activity-title"
      className="fixed inset-0 z-50 flex items-end lg:items-center justify-center bg-black/45 backdrop-blur-sm p-0 lg:p-6"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-[var(--color-page)] w-full lg:w-[560px] max-h-[95vh] rounded-t-2xl lg:rounded-2xl shadow-2xl flex flex-col overflow-hidden"
      >
        <header className="flex items-start justify-between gap-3 px-5 lg:px-6 pt-5 pb-3 border-b border-[var(--color-edify-divider)]">
          <div className="min-w-0 flex items-start gap-3">
            <span className="h-10 w-10 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
              <Play size={18} />
            </span>
            <div className="min-w-0">
              <h2 id="start-activity-title" className="text-body-lg lg:text-h-xs font-extrabold tracking-tight">
                Start activity
              </h2>
              <p className="text-caption text-muted mt-0.5 leading-snug">
                Confirm the details. Starting moves this into your active work — evidence + completion become available.
              </p>
            </div>
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

        <div className="flex-1 overflow-y-auto px-5 lg:px-6 py-4 space-y-3">
          {/* Activity summary */}
          <section className="card p-3.5">
            <h3 className="text-body-lg font-extrabold tracking-tight">{plan.label}</h3>
            {plan.schoolName && <p className="text-caption text-muted mt-0.5">{plan.schoolName}{plan.clusterName ? ` · ${plan.clusterName}` : ""}</p>}
            <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Row Icon={Calendar}      label="Scheduled"  value={plan.scheduledFor} />
              {plan.ownerLabel  && <Row Icon={Users}      label="Owner"       value={plan.ownerLabel} />}
              {plan.purpose     && <Row Icon={Target}     label="Purpose"     value={plan.purpose} fullSpan />}
              {plan.costLabel   && <Row Icon={ClipboardList} label="Cost rollup" value={plan.costLabel} />}
            </dl>
          </section>

          {/* Required evidence */}
          {plan.evidenceRequired && plan.evidenceRequired.length > 0 && (
            <section className="card p-3.5">
              <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                <ClipboardList size={13} className="text-[var(--color-edify-muted)]" />
                Evidence required
              </h3>
              <p className="text-caption text-muted mt-0.5">
                Bring or capture these before you mark the activity complete.
              </p>
              <ul className="mt-2 space-y-1.5">
                {plan.evidenceRequired.map((e) => (
                  <li key={e} className="flex items-start gap-2 text-body">
                    <CheckCircle2 size={12} className="text-emerald-600 mt-1 shrink-0" />
                    <span>{e}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Future-date warning */}
          {plan.status === "scheduled" && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 flex items-start gap-2.5">
              <AlertTriangle size={13} className="text-amber-700 mt-0.5 shrink-0" />
              <p className="text-caption text-amber-900 leading-snug">
                This activity is scheduled for a future date. Confirm you want to start it early — the timestamp will be captured now.
              </p>
            </div>
          )}
        </div>

        <footer className="px-5 lg:px-6 py-3 border-t border-[var(--color-edify-divider)] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-semibold hover:bg-[var(--color-edify-soft)]/40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleStart}
            disabled={submitting}
            className={cn(
              "h-10 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)] transition-colors",
              submitting
                ? "bg-[var(--color-edify-muted)] cursor-not-allowed"
                : "bg-emerald-600 hover:bg-emerald-500",
            )}
          >
            <Play size={13} />
            {submitting ? "Starting…" : "Start now"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function Row({
  Icon,
  label,
  value,
  fullSpan,
}: {
  Icon:     typeof Calendar;
  label:    string;
  value:    string;
  fullSpan?: boolean;
}) {
  return (
    <div className={fullSpan ? "sm:col-span-2" : ""}>
      <dt className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted inline-flex items-center gap-1.5">
        <Icon size={11} />
        {label}
      </dt>
      <dd className="text-body font-semibold text-[var(--color-edify-text)] mt-0.5">{value}</dd>
    </div>
  );
}
