"use server";

// Record an assignment made from a planning gap board. Canonical Bucket-C
// shape: resolve actor, gate by role, persist to the assignment overlay, emit
// one audit row + notify the assignee (partner inbox for delegated work),
// revalidate, return a discriminated union.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { recordGapAssignment, type GapAssignmentOwner } from "@/lib/planning/assignment-overlay";
import { emitAudit, emitNotification } from "./audit";

export type AssignGapInput = {
  gapId?: string;
  title: string;
  schoolOrCluster: string;
  owner: GapAssignmentOwner;
  ownerName?: string;
  monthLabel?: string;
  week?: number;
  notes?: string;
};

export type AssignGapResult =
  | { ok: true; id: string }
  | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" };

// Who can assign from the gap boards — a PLANNING write. Only the planning roles
// (CCEO assigns own/partner; PL assigns supervised/partner). CD doesn't plan
// (flags to PL instead) and IA only verifies — both removed to mirror the
// backend ACTIVITY_ASSIGN gate.
const ASSIGN_ROLES = new Set(["CCEO", "CountryProgramLead", "Admin"]);

export async function assignGapActivity(input: AssignGapInput): Promise<AssignGapResult> {
  const user = await getCurrentUser();
  if (!ASSIGN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.title?.trim() || !input.owner) return { ok: false, reason: "INVALID_INPUT" };

  const ownerName = input.ownerName?.trim() || (input.owner === "myself" ? user.name : undefined);

  const rec = recordGapAssignment({
    gapId: input.gapId,
    title: input.title.trim(),
    schoolOrCluster: input.schoolOrCluster,
    owner: input.owner,
    ownerName,
    monthLabel: input.monthLabel,
    week: input.week,
    notes: input.notes?.trim() || undefined,
    assignedById: user.staffId,
    assignedByName: user.name,
  });

  emitAudit({
    action: "planning.activityAssigned",
    subjectKind: "PlanActivityAssignment",
    subjectId: rec.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { title: rec.title, school: rec.schoolOrCluster, owner: rec.owner, ownerName, month: rec.monthLabel, week: rec.week },
  });

  // Delegated work pings the assignee. Partner/facilitator → partner inbox;
  // staff → the named staffer's proxy; self → a personal confirmation.
  const when = rec.monthLabel ? `${rec.monthLabel}${rec.week ? ` · Wk ${rec.week}` : ""}` : "this cycle";
  if (input.owner === "partner" || input.owner === "partner_facilitator") {
    emitNotification({
      userId: "PARTNER",
      template: "planning.activityAssigned",
      channel: "Inbox",
      title: `New assignment: ${rec.title}`,
      body: `${user.name} assigned "${rec.title}" (${rec.schoolOrCluster}) to ${ownerName ?? "your team"} for ${when}.`,
      href: "/partner/assignments",
    });
  } else {
    emitNotification({
      userId: input.owner === "myself" ? user.staffId : "STAFF",
      template: "planning.activityAssigned",
      channel: "Inbox",
      title: `Assigned: ${rec.title}`,
      body: `"${rec.title}" (${rec.schoolOrCluster}) is on the plan for ${when}.`,
      href: "/my-plan",
    });
  }

  try {
    revalidatePath("/planning");
    revalidatePath("/my-plan");
    revalidatePath("/partner/assignments");
    revalidatePath("/notifications");
  } catch {
    /* outside request scope — fine */
  }

  return { ok: true, id: rec.id };
}
