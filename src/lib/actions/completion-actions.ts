"use server";

// Confirm a visit/training completion (the Salesforce Completion Gate on
// /visits + /trainings). Canonical Bucket-C shape: resolve actor, gate by
// role, validate the entered Salesforce ID, persist to the completion overlay,
// emit one audit row + notify IA for verification, revalidate, return a
// discriminated union (echoing the exact entered ID — ID-consistency).

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { recordCompletion } from "@/lib/execution/completion-overlay";
import { emitAudit, emitNotification } from "./audit";

export type ConfirmCompletionInput = {
  activityId: string;
  activityType: string;
  schoolName: string;
  salesforceId: string;
  salesforceIdKind?: string;
  teachers?: number;
  leaders?: number;
};

export type ConfirmCompletionResult =
  | { ok: true; activityId: string; salesforceId: string }
  | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" };

// Field workers (and their leads) confirm completion. Partners confirm their
// own delivered visits.
const ROLES = new Set([
  "CCEO", "CountryProgramLead", "ImpactAssessment", "CountryDirector", "Admin",
  "PartnerAdmin", "PartnerFieldOfficer",
]);

export async function confirmActivityCompletion(input: ConfirmCompletionInput): Promise<ConfirmCompletionResult> {
  const user = await getCurrentUser();
  if (!ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const sfId = input.salesforceId?.trim() ?? "";
  if (sfId.length < 3 || !input.activityId) return { ok: false, reason: "INVALID_INPUT" };

  recordCompletion({
    activityId: input.activityId,
    activityType: input.activityType,
    schoolName: input.schoolName,
    salesforceId: sfId,
    salesforceIdKind: input.salesforceIdKind,
    teachers: input.teachers,
    leaders: input.leaders,
    confirmedById: user.staffId,
    confirmedByName: user.name,
  });

  emitAudit({
    action: "activity.completionConfirmed",
    subjectKind: "ActivityCompletion",
    subjectId: input.activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { salesforceId: sfId, activityType: input.activityType, school: input.schoolName, teachers: input.teachers, leaders: input.leaders },
  });

  // Hand off to IA: a confirmed Salesforce ID is what the IA copies into
  // Salesforce to verify the activity counts for donor metrics.
  emitNotification({
    userId: "IMPACT_ASSESSMENT",
    template: "activity.completionConfirmed",
    channel: "Inbox",
    title: `Completion to verify: ${input.schoolName}`,
    body: `${user.name} confirmed ${input.activityType} (${input.schoolName}) with Salesforce ID ${sfId}.`,
    href: "/data-verification",
  });

  try {
    revalidatePath("/visits");
    revalidatePath("/trainings");
    revalidatePath("/data-verification");
    revalidatePath("/notifications");
  } catch {
    /* outside request scope — fine */
  }

  return { ok: true, activityId: input.activityId, salesforceId: sfId };
}
