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
import { reviewerPlan } from "@/lib/reschedule/routing";
import type { RescheduleActor } from "@/lib/reschedule/types";

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

  revalidatePath("/messages");
  revalidatePath("/partner/schedule");
}

// Start Activity. Flips the scheduled-plan status to In Progress.
// Mock today — Phase 4 swaps the body for a real DB write. The
// revalidate ensures the card flips from "Reschedule + Start" to
// "Complete Activity" on the next render.
export async function startActivityAction(formData: FormData): Promise<void> {
  const activityId    = String(formData.get("activityId") ?? "");
  const activityLabel = String(formData.get("activityLabel") ?? "");
  if (!activityId) return;

  // eslint-disable-next-line no-console
  console.info("[start-activity] in-progress", { activityId, activityLabel, at: new Date().toISOString() });

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
