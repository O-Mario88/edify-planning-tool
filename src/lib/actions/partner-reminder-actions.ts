"use server";

// "Bump" a partner whose assigned activity still has no delivery date.
// Sends a reminder notification + records an audit row. Canonical Bucket-C
// shape (resolve actor, gate, emit, revalidate, discriminated union).

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotification } from "./audit";

export type RemindPartnerInput = {
  schoolId: string;
  schoolName: string;
  kind: "visit" | "training";
  activityNumber: number;
  partnerName?: string;
};

export type RemindPartnerResult =
  | { ok: true; sentTo: string }
  | { ok: false; reason: "FORBIDDEN" };

// Account owners (CCEO/PL) and leadership chase partner scheduling.
const NUDGE_ROLES = new Set(["CCEO", "CountryProgramLead", "CountryDirector", "Admin"]);

export async function remindPartnerToSchedule(input: RemindPartnerInput): Promise<RemindPartnerResult> {
  const user = await getCurrentUser();
  if (!NUDGE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const who = input.partnerName?.trim() || "Partner";
  const activity = `${input.kind === "visit" ? "Visit" : "Training"} ${input.activityNumber} · ${input.schoolName}`;

  emitAudit({
    action: "partner.scheduleReminderSent",
    subjectKind: "CoreActivity",
    subjectId: `${input.schoolId}:${input.kind}:${input.activityNumber}`,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { schoolName: input.schoolName, kind: input.kind, partner: who },
  });

  // Notify the partner inbox (proxy userId in mock-land — production resolves
  // the partner org's active officers from the assignment).
  emitNotification({
    userId: "PARTNER",
    template: "partner.scheduleReminder",
    channel: "Inbox",
    title: `Reminder: schedule ${activity}`,
    body: `${user.name} is asking ${who} to set a delivery date for ${activity}. Please schedule it from your assignments.`,
    href: "/partner/schedule",
  });

  try {
    revalidatePath("/planning");
    revalidatePath("/partner/schedule");
    revalidatePath("/notifications");
  } catch {
    /* outside request scope — fine */
  }

  return { ok: true, sentTo: who };
}
