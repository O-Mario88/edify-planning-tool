"use client";

// ScheduledPlanCard — the unified card every "scheduled activity"
// surface should render.
//
// Spec §1 + §8: every scheduled card shows two actions —
// Reschedule + Start Activity — but the visibility flips with status:
//
//   scheduled / due_today / due_this_week / rescheduled  → both
//   in_progress                                          → Complete only
//   evidence_required                                    → Upload Evidence
//   completion_submitted / awaiting_review               → status chip
//   completed                                            → View Report
//   cancelled                                            → no actions
//   missed                                               → Reschedule + Mark Missed
//
// Buttons are visually weighted: Start is the strong primary CTA on
// every device; Reschedule is the calmer secondary. On mobile Start
// is full-width.

import { useState } from "react";
import Link from "next/link";
import {
  Building2,
  Calendar,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Eye,
  FileText,
  Play,
  Target,
  Upload,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { RescheduleDrawer, type RescheduleSubmitInput } from "@/components/reschedule/RescheduleDrawer";
import { StartActivityDrawer } from "./StartActivityDrawer";
import { STATUS_META, actionsForStatus } from "@/lib/scheduled-plan/status";
import { reasonLabels } from "@/lib/reschedule/reasons";
import type { ScheduledPlan } from "@/lib/scheduled-plan/types";

const STATUS_TONE: Record<(typeof STATUS_META)[keyof typeof STATUS_META]["tone"], string> = {
  slate:   "bg-slate-100 text-slate-700 border-slate-200",
  blue:    "bg-blue-50 text-blue-800 border-blue-200",
  emerald: "bg-emerald-50 text-emerald-800 border-emerald-200",
  amber:   "bg-amber-50 text-amber-800 border-amber-200",
  rose:    "bg-rose-50 text-rose-800 border-rose-200",
  violet:  "bg-violet-50 text-violet-700 border-violet-200",
};

export function ScheduledPlanCard({
  plan,
  /** Server actions wired by the host page. */
  rescheduleAction,
  startAction,
  /** Optional href if the activity has a detail page. */
  detailHref,
}: {
  plan:             ScheduledPlan;
  rescheduleAction: (formData: FormData) => Promise<void> | void;
  startAction:      (formData: FormData) => Promise<void> | void;
  detailHref?:      string;
}) {
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [startOpen, setStartOpen] = useState(false);

  const meta = STATUS_META[plan.status];
  const actions = actionsForStatus(plan.status);

  async function onReschedule(input: RescheduleSubmitInput) {
    const fd = new FormData();
    fd.append("activityId",    input.activityId);
    fd.append("activityType",  input.activityType);
    fd.append("activityLabel", input.activityLabel);
    fd.append("schoolName",    input.schoolName ?? "");
    fd.append("originalDate",  input.originalDate);
    fd.append("newDate",       input.newDate);
    fd.append("reasonKeys",    input.reasonKeys.join(","));
    fd.append("reasonLabels",  reasonLabels(input.reasonKeys).join("|"));
    fd.append("notes",         input.notes ?? "");
    fd.append("actor",         plan.actor);
    await rescheduleAction(fd);
  }

  return (
    <>
      <article className="card p-3.5 lg:p-5">
        <header className="flex items-start gap-3 flex-wrap">
          <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
            <Building2 size={18} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-body-lg font-extrabold tracking-tight">{plan.label}</h3>
              <span
                className={cn(
                  "inline-flex items-center px-2 py-[2px] rounded-md text-tiny font-extrabold uppercase tracking-[0.06em] border",
                  STATUS_TONE[meta.tone],
                )}
              >
                {meta.label}
              </span>
            </div>
            {(plan.schoolName || plan.clusterName) && (
              <div className="text-caption text-muted mt-1">
                {plan.schoolName ?? plan.clusterName}
                {plan.district ? ` · ${plan.district}` : ""}
              </div>
            )}
          </div>
        </header>

        {/* Meta strip — date / owner / purpose */}
        <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-caption">
          <MetaRow Icon={Calendar} label="Scheduled" value={plan.scheduledFor} />
          {plan.ownerLabel && <MetaRow Icon={Users} label="Owner" value={plan.ownerLabel} />}
          {plan.purpose && <MetaRow Icon={Target} label="Purpose" value={plan.purpose} fullSpan />}
          {plan.evidenceRequired && plan.evidenceRequired.length > 0 && (
            <MetaRow
              Icon={ClipboardList}
              label="Evidence required"
              value={plan.evidenceRequired.join(" · ")}
              fullSpan
            />
          )}
          {plan.costLabel && <MetaRow Icon={ClipboardList} label="Cost" value={plan.costLabel} />}
        </dl>

        {/* Action row */}
        <ActionRow
          actions={actions}
          onReschedule={() => setRescheduleOpen(true)}
          onStart={() => setStartOpen(true)}
          detailHref={detailHref}
        />
      </article>

      <RescheduleDrawer
        open={rescheduleOpen}
        onClose={() => setRescheduleOpen(false)}
        activityId={plan.id}
        activityType={plan.activityType}
        activityLabel={plan.label}
        schoolName={plan.schoolName}
        originalDate={plan.scheduledFor}
        actor={plan.actor}
        onSubmit={onReschedule}
      />

      <StartActivityDrawer
        open={startOpen}
        onClose={() => setStartOpen(false)}
        plan={plan}
        startAction={startAction}
      />
    </>
  );
}

// ─────────────────────────── sub-components ────────────────────────────

function MetaRow({
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
      <div className="text-tiny font-extrabold uppercase tracking-[0.06em] text-muted inline-flex items-center gap-1.5">
        <Icon size={11} />
        {label}
      </div>
      <div className="text-body font-semibold text-[var(--color-edify-text)] mt-0.5 leading-snug">{value}</div>
    </div>
  );
}

function ActionRow({
  actions,
  onReschedule,
  onStart,
  detailHref,
}: {
  actions:      ReturnType<typeof actionsForStatus>;
  onReschedule: () => void;
  onStart:      () => void;
  detailHref?:  string;
}) {
  if (actions.length === 0) return null;
  if (actions.includes("awaiting_review_chip")) {
    return (
      <div className="mt-4 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-blue-50 text-blue-800 border border-blue-200 text-caption font-semibold">
        <CheckCircle2 size={12} />
        Awaiting review
      </div>
    );
  }

  const showReschedule = actions.includes("reschedule");
  const showStart      = actions.includes("start");
  const showComplete   = actions.includes("complete");
  const showUpload     = actions.includes("upload_evidence");
  const showViewReport = actions.includes("view_report");
  const showMissed     = actions.includes("mark_missed");

  // Layout: Start (primary, full-width on mobile) + Reschedule
  // (secondary). Or single primary for completion / evidence states.
  return (
    <div className="mt-4 flex flex-col-reverse sm:flex-row sm:items-center gap-2">
      {showReschedule && (
        <button
          type="button"
          onClick={onReschedule}
          className="h-10 px-3.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center justify-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 w-full sm:w-auto"
        >
          <CalendarClock size={13} className="text-muted" />
          Reschedule
        </button>
      )}
      {showStart && (
        <button
          type="button"
          onClick={onStart}
          className="h-10 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-body font-extrabold inline-flex items-center justify-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)] flex-1 sm:flex-none"
        >
          <Play size={13} />
          Start activity
        </button>
      )}
      {showComplete && (
        <Link
          href={detailHref ?? "#"}
          className="h-10 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-body font-extrabold inline-flex items-center justify-center gap-1.5 flex-1 sm:flex-none"
        >
          <CheckCircle2 size={13} />
          Complete activity
        </Link>
      )}
      {showUpload && (
        <Link
          href={detailHref ?? "#"}
          className="h-10 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-body font-extrabold inline-flex items-center justify-center gap-1.5 flex-1 sm:flex-none"
        >
          <Upload size={13} />
          Upload Evidence
        </Link>
      )}
      {showViewReport && (
        <Link
          href={detailHref ?? "#"}
          className="h-10 px-4 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center justify-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 flex-1 sm:flex-none"
        >
          <FileText size={13} className="text-muted" />
          View report
        </Link>
      )}
      {showMissed && (
        <button
          type="button"
          className="h-10 px-3.5 rounded-lg border border-rose-300 bg-rose-50 text-rose-800 text-body font-semibold inline-flex items-center justify-center gap-1.5 hover:bg-rose-100 w-full sm:w-auto"
        >
          <Eye size={13} />
          Explain missed
        </button>
      )}
    </div>
  );
}
