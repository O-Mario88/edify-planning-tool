"use server";

// Project activity execution→payment pipeline — server actions.
//
// A partner-assigned project activity moves through the same verified path as
// any partner activity: schedule → evidence → staff accept → Salesforce ID →
// IA verify → accountant pay. Each transition is role-gated (canPerform),
// validity-checked (transition machine), audited, and notified — mirroring
// src/lib/actions/partner-actions.ts conventions. Payment is hard-gated to
// IAVerified by the state machine.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  applyProjectWorkflowAction,
  projectActivityById,
  validateSalesforceId,
  type WorkflowPatch,
} from "@/lib/projects/project-activities";
import {
  canPerform,
  NEXT_ACTOR,
  ACTION_LABEL,
  type ProjectWorkflowAction,
  type ActorKind,
} from "@/lib/projects/project-partner-workflow";
import { projectById } from "@/lib/special-projects-mock";

export type WorkflowActionResult =
  | { ok: true; status: string }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "FAILED"; message: string };

function revalidatePipelineSurfaces() {
  try {
    revalidatePath("/special-projects/pipeline");
    revalidatePath("/special-projects/schools");
    revalidatePath("/dashboards/project-coordinator");
    revalidatePath("/data-verification");
    revalidatePath("/dashboards/accountant");
  } catch {
    /* outside request scope */
  }
}

// Map the next actor kind → notification recipients (role tokens / partner id).
function recipientsForNextActor(kind: ActorKind | undefined, partnerId?: string): string[] {
  switch (kind) {
    case "partner": return partnerId ? [partnerId] : [];
    case "staff": return ["CCEO", "CountryProgramLead", "ProjectCoordinator"];
    case "ia": return ["ImpactAssessment"];
    case "accountant": return ["ProgramAccountant"];
    default: return [];
  }
}

/**
 * Run one workflow transition on a project activity. The UI passes the action
 * it wants; this gates by role, validates, mutates, audits, and notifies the
 * next-step owner. `patch` carries evidence note / return reason / Salesforce
 * id / payment reference as the action requires.
 */
export async function runProjectWorkflowAction(
  activityId: string,
  action: ProjectWorkflowAction,
  patch: WorkflowPatch = {},
): Promise<WorkflowActionResult> {
  const user = await getCurrentUser();
  if (!canPerform(user.role, action)) return { ok: false, reason: "FORBIDDEN" };

  const activity = projectActivityById(activityId);
  if (!activity) return { ok: false, reason: "FAILED", message: "Activity not found." };

  // Salesforce prefix rule (SV- for visits, TS- for trainings) — same as core.
  if (action === "enterSalesforceId") {
    const v = validateSalesforceId(patch.salesforceActivityId ?? "", activity.activityType);
    if (!v.ok) return { ok: false, reason: "FAILED", message: v.reason };
  }
  if (action === "returnEvidence" || action === "rejectWork" || action === "iaReturn") {
    if (!patch.returnReason?.trim()) return { ok: false, reason: "FAILED", message: "A reason is required." };
  }
  // Auto-generate a payment reference at clearance when none supplied.
  if (action === "clearPayment" && !patch.paymentRef) {
    patch = { ...patch, paymentRef: `PMT-${activity.projectId}-${activity.id}` };
  }

  const res = applyProjectWorkflowAction(activityId, action, patch);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  const updated = res.activity;

  const project = projectById(updated.projectId);
  emitAudit({
    action: `projectActivity.${action}`,
    subjectKind: "ProjectActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      projectId: updated.projectId,
      schoolId: updated.schoolId,
      newStatus: updated.workflowStatus,
      salesforceActivityId: updated.salesforceActivityId,
      paymentRef: updated.paymentRef,
      reason: patch.returnReason,
    },
  });

  const recipients = recipientsForNextActor(
    updated.workflowStatus ? NEXT_ACTOR[updated.workflowStatus] : undefined,
    updated.assignedToPartnerId ?? updated.partnerId,
  );
  if (recipients.length) {
    emitNotificationFanOut(recipients, {
      template: `projectActivity.${action}`,
      channel: "Inbox",
      title: `${project?.projectShortName ?? "Project"} · ${ACTION_LABEL[action]}`,
      body: `${updated.activityType} — now ${updated.workflowStatus}.`,
      href: "/special-projects/pipeline",
    });
  }

  revalidatePipelineSurfaces();
  return { ok: true, status: updated.workflowStatus ?? "" };
}
