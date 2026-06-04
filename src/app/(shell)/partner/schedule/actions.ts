"use server";

// Reschedule + Start Activity + review server actions for the
// partner schedule surface. The reschedule action emits a system
// message to the routed reviewers; Start Activity transitions
// status to In Progress; the review action handles
// Confirm/Return/Reject outcomes.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import {
  emitReschedule,
  emitWorkRejected,
  emitWorkReturned,
} from "@/lib/messages-v2/system-events";
import { emitAudit, emitNotificationFanOut } from "@/lib/actions/audit";
import { markPlanStarted } from "@/lib/scheduled-plan/started-overlay";
import { reviewerPlan } from "@/lib/reschedule/routing";
import type { RescheduleActor } from "@/lib/reschedule/types";

// Month + week-of-month bucket for a date string, or null if unparseable.
// A reschedule that crosses a bucket boundary shifts cost between budget
// periods, so it should trigger a budget / MFR regeneration downstream.
function periodBucket(dateStr: string): { monthIso: string; week: number } | null {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return null;
  return {
    monthIso: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
    week: Math.ceil(d.getDate() / 7),
  };
}

export async function submitRescheduleAction(formData: FormData): Promise<void> {
  const user = await getCurrentUser();

  const actor = String(formData.get("actor") ?? "staff") as RescheduleActor;
  const activityLabel = String(formData.get("activityLabel") ?? "");
  const activityType  = String(formData.get("activityType")  ?? "");
  const schoolName    = String(formData.get("schoolName")    ?? "") || undefined;
  const originalDate  = String(formData.get("originalDate")  ?? "");
  const newDate       = String(formData.get("newDate")       ?? "");
  const reasonLabelsCsv = String(formData.get("reasonLabels") ?? "");
  const notes = String(formData.get("notes") ?? "").trim() || undefined;

  if (!activityLabel || !newDate || !reasonLabelsCsv) {
    return; // Defence in depth — the drawer pre-validates.
  }

  const labels = reasonLabelsCsv.split("|").filter(Boolean);

  // Pick recipients off the routing rules. The drawer already showed
  // these chips to the submitter; we re-resolve here so a client can't
  // fabricate a recipient set.
  const plan = reviewerPlan(actor);

  emitReschedule({
    activityLabel,
    activityType,
    schoolName,
    actorName:        user.name,
    actorRole:        user.role,
    actor,
    reasonLabels:     labels,
    notes,
    originalDate,
    newDate,
    recipientUserIds: plan.userIds,
  });

  // Cross-workflow contract: if the new date lands in a different budget
  // period (month or week) than the original, the cost moves between buckets
  // — fire a recalc event so the budget + Monthly Fund Request regenerate.
  // (In the mock the budget reads a deterministic generator, so the numbers
  //  are stable; this is the event/notification + revalidation seam a real
  //  recalc job hooks into.)
  const from = periodBucket(originalDate);
  const to = periodBucket(newDate);
  const periodChanged = !from || !to || from.monthIso !== to.monthIso || from.week !== to.week;

  if (periodChanged) {
    emitAudit({
      action: "budget.recalcRequested",
      subjectKind: "PlannedActivity",
      subjectId: activityLabel,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: {
        reason: "reschedule",
        activityType,
        fromPeriod: from ? `${from.monthIso} W${from.week}` : originalDate,
        toPeriod: to ? `${to.monthIso} W${to.week}` : newDate,
      },
    });
    emitNotificationFanOut(["PROGRAM_LEAD", "PROGRAM_ACCOUNTANT", "COUNTRY_DIRECTOR"], {
      template: "budget.recalcRequested",
      channel: "Inbox",
      title: "Budget impact: activity rescheduled across a period",
      body: `"${activityLabel}" moved to ${newDate}. Regenerate the affected month's budget + fund request.`,
      href: "/monthly-fund-request",
    });
    try {
      revalidatePath("/budget");
      revalidatePath("/monthly-fund-request");
    } catch {
      /* outside request scope — fine */
    }
  }

  revalidatePath("/messages");
  revalidatePath("/partner/schedule");
}

// Start Activity. Flips the scheduled-plan status to In Progress by recording
// the start in the started-plan overlay (the schedule page applies it onto the
// plan list), and emits an audit row. The revalidate then re-renders the card
// from "Reschedule + Start" to its in-progress affordances.
export async function startActivityAction(formData: FormData): Promise<void> {
  const user = await getCurrentUser();
  const activityId    = String(formData.get("activityId") ?? "");
  const activityLabel = String(formData.get("activityLabel") ?? "");
  if (!activityId) return;

  markPlanStarted(activityId, { id: user.staffId, name: user.name });

  emitAudit({
    action: "scheduledPlan.started",
    subjectKind: "ScheduledPlan",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { activityLabel },
  });

  revalidatePath("/partner/schedule");
  revalidatePath("/partner/assignments");
  revalidatePath("/messages");
}

// Confirm = no-op message; Return = emit returned-for-correction;
// Reject = emit rejection (urgent, PL + CD copied if serious).
export async function submitReviewAction(formData: FormData): Promise<void> {
  const outcome      = String(formData.get("outcome") ?? "confirm");
  const activityLabel = String(formData.get("activityLabel") ?? "");
  const schoolName    = String(formData.get("schoolName")    ?? "");
  const reasonLabel   = String(formData.get("reasonLabel")   ?? "");
  const reviewerComment = String(formData.get("reviewerComment") ?? "");
  const dueDate         = String(formData.get("dueDate") ?? "");
  const requiredAction  = String(formData.get("requiredAction") ?? "");
  const partnerUserIds  = String(formData.get("partnerUserIds") ?? "").split(",").filter(Boolean);
  const reviewerUserIds = String(formData.get("reviewerUserIds") ?? "").split(",").filter(Boolean);

  if (outcome === "return") {
    emitWorkReturned({
      activityLabel,
      schoolName,
      reason:         reasonLabel,
      reviewerComment,
      dueDate,
      partnerUserIds,
    });
  } else if (outcome === "reject") {
    emitWorkRejected({
      activityLabel,
      schoolName,
      reason:         reasonLabel,
      reviewerComment,
      requiredAction,
      partnerUserIds,
      reviewerUserIds,
    });
  }
  // Confirm path doesn't emit a system message — it just transitions
  // status to "Awaiting PL Approval". Real DB write lands in Phase 4.

  revalidatePath("/messages");
}
