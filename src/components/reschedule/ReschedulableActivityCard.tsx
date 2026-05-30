"use client";

// ReschedulableActivityCard — small showcase card that mounts a
// "Reschedule" button next to a single scheduled activity. Clicking
// the button opens the RescheduleDrawer; submit calls a server
// action that emits the system message to the routed reviewers.
//
// This is the demo wiring — production embeds the same drawer
// behind every existing "Reschedule" CTA across MyActivities,
// PartnerSchedule, CceoMonthPlanner, etc.

import { useState } from "react";
import { Calendar, CalendarClock } from "lucide-react";
import { RescheduleDrawer, type RescheduleSubmitInput } from "./RescheduleDrawer";
import type { RescheduleActor, ReschedulableActivity } from "@/lib/reschedule/types";
import { reasonLabels } from "@/lib/reschedule/reasons";

export function ReschedulableActivityCard({
  activityId,
  activityType,
  activityLabel,
  schoolName,
  originalDate,
  actor,
  actorName,
  actorRole,
  submitAction,
}: {
  activityId:    string;
  activityType:  ReschedulableActivity;
  activityLabel: string;
  schoolName?:   string;
  originalDate:  string;
  actor:         RescheduleActor;
  actorName:     string;
  actorRole:     string;
  /** Server action — receives the resolved payload + the routed
   *  reviewer userIds list and emits the system message. */
  submitAction:  (formData: FormData) => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [lastRescheduled, setLastRescheduled] = useState<string | null>(null);

  async function handleSubmit(input: RescheduleSubmitInput) {
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
    fd.append("actor",         actor);
    fd.append("actorName",     actorName);
    fd.append("actorRole",     actorRole);
    await submitAction(fd);
    setLastRescheduled(input.newDate);
  }

  return (
    <article className="card p-3.5 lg:p-5 flex items-start gap-4 flex-wrap lg:flex-nowrap">
      <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Calendar size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <h3 className="text-body-lg font-extrabold tracking-tight">{activityLabel}</h3>
        {schoolName && <div className="text-caption text-muted mt-0.5">{schoolName}</div>}
        <div className="text-caption text-muted mt-1.5 tabular">
          Scheduled: <span className="text-body-lg font-semibold">{originalDate}</span>
        </div>
        {lastRescheduled && (
          <div className="text-caption mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-800 font-semibold">
            <CalendarClock size={11} />
            Rescheduled to {lastRescheduled} · reviewers notified
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-10 px-4 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40"
      >
        <CalendarClock size={13} className="text-muted" />
        Reschedule
      </button>

      <RescheduleDrawer
        open={open}
        onClose={() => setOpen(false)}
        activityId={activityId}
        activityType={activityType}
        activityLabel={activityLabel}
        schoolName={schoolName}
        originalDate={originalDate}
        actor={actor}
        onSubmit={handleSubmit}
      />
    </article>
  );
}
