"use server";

// Portfolio actions — partner delegation that NEVER transfers ownership.
//
// Assigning a partner to a school delegates who *delivers* an activity. The
// school stays in the account owner's portfolio, counts, dashboard, planning,
// and analytics. Cancelling a delegation simply ends the partner's involvement;
// ownership is untouched throughout.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import {
  addPartnerAssignment,
  setPartnerAssignmentStatus,
  partnerAssignments,
} from "@/lib/portfolio/partner-assignments";

// Who may delegate execution on a school: the account owner themselves, their
// supervising Program Lead / Country Director, or Admin.
const DELEGATION_ROLES = new Set<string>(["CountryProgramLead", "CountryDirector", "Admin"]);

function revalidatePortfolioSurfaces() {
  revalidatePath("/portfolio");
  revalidatePath("/data-intake");
}

export type AssignPartnerResult =
  | { ok: false; reason: "FORBIDDEN" | "SCHOOL_NOT_FOUND" | "INVALID_INPUT" }
  | { ok: true; id: string };

export async function assignPartnerToSchool(input: {
  schoolId: string;
  partnerName: string;
  interventionArea?: string;
  note?: string;
}): Promise<AssignPartnerResult> {
  const user = await getCurrentUser();
  const school = intakeSchools.find((s) => s.schoolId === input.schoolId);
  if (!school) return { ok: false, reason: "SCHOOL_NOT_FOUND" };

  // Owner of this school, or a delegation-capable role.
  const owner = resolveOwner(school.assignedCceo);
  const isOwner = owner.status === "matched" && owner.staffId === user.staffId;
  if (!isOwner && !DELEGATION_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const partnerName = input.partnerName.trim();
  if (!partnerName) return { ok: false, reason: "INVALID_INPUT" };

  const row = addPartnerAssignment({
    schoolId: input.schoolId,
    partnerName,
    interventionArea: input.interventionArea?.trim() || undefined,
    note: input.note?.trim() || undefined,
    assignedByName: user.name,
    assignedByStaffId: user.staffId,
  });

  emitAudit({
    action: "portfolio.partnerDelegated",
    subjectKind: "School",
    subjectId: input.schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { partnerName, interventionArea: row.interventionArea, schoolName: school.schoolName, ownership: "unchanged" },
  });
  // Tell the account owner their school now has a delegated partner (ownership
  // unchanged) — unless they did it themselves.
  if (owner.status === "matched" && owner.staffId !== user.staffId) {
    emitNotificationFanOut([owner.staffId], {
      template: "portfolio.partnerDelegated",
      channel: "Inbox",
      title: "A partner was assigned to your school",
      body: `${partnerName} will deliver work at ${school.schoolName}. The school stays in your portfolio.`,
      href: "/portfolio",
    });
  }
  revalidatePortfolioSurfaces();
  return { ok: true, id: row.id };
}

export type CancelPartnerResult =
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" }
  | { ok: true; id: string };

export async function cancelPartnerAssignment(id: string): Promise<CancelPartnerResult> {
  const user = await getCurrentUser();
  const row = partnerAssignments.find((p) => p.id === id);
  if (!row) return { ok: false, reason: "NOT_FOUND" };

  const school = intakeSchools.find((s) => s.schoolId === row.schoolId);
  const owner = school ? resolveOwner(school.assignedCceo) : { status: "none" as const };
  const isOwner = owner.status === "matched" && owner.staffId === user.staffId;
  if (!isOwner && !DELEGATION_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  setPartnerAssignmentStatus(id, "Cancelled");
  emitAudit({
    action: "portfolio.partnerDelegationCancelled",
    subjectKind: "School",
    subjectId: row.schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { partnerName: row.partnerName, ownership: "unchanged" },
  });
  revalidatePortfolioSurfaces();
  return { ok: true, id };
}
