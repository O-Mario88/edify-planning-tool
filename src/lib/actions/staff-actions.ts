"use server";

// Staff onboarding — server actions. Phase 1: create a staff record.
//
// Workflow owner is CD / HR (Admin retained for the demo). Creating a staff
// member does NOT make them operational — it produces account + role +
// supervisor. Schools (IA), primary district, and targets come later; the
// activation engine flips status to Active only when all are connected.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { DEMO_USERS } from "@/lib/auth-public";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  addOrgStaff,
  createdOrgStaff,
  orgStaff,
  setStaffPrimaryDistrict,
  setStaffSupervisor,
  supervisorRoleFor,
  type OrgStaff,
  type StaffStatus,
} from "@/lib/org/supervision";
import { validateNewStaff, labelForRole, type NewStaffInput } from "@/lib/intake/staff-creation-core";
import { addStaffTargetProfile } from "@/lib/targets/staff-target-profile";
import { canActivateStaff } from "@/lib/org/staff-activation";
import type { EdifyRole } from "@/lib/auth";

/** Roles allowed to create/onboard staff. CD + HR own the workflow; Admin kept. */
const STAFF_ADMIN_ROLES = new Set<string>(["CountryDirector", "HumanResource", "Admin"]);

export type StaffActionResult =
  | { ok: true; id: string; status: StaffStatus }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_INPUT"; errors: Record<string, string> };

let staffSeq = 0;

function existingEmails(): Set<string> {
  const out = new Set<string>();
  for (const u of Object.values(DEMO_USERS)) out.add(u.email.trim().toLowerCase());
  for (const s of createdOrgStaff()) if (s.email) out.add(s.email.trim().toLowerCase());
  return out;
}

export async function createStaff(input: NewStaffInput): Promise<StaffActionResult> {
  const user = await getCurrentUser();
  if (!STAFF_ADMIN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const v = validateNewStaff(input, existingEmails(), (id) => orgStaff(id)?.role);
  if (!v.ok) return { ok: false, reason: "INVALID_INPUT", errors: v.errors };

  const role = input.role as EdifyRole;
  const supervisorId = input.supervisorStaffId?.trim() || null;
  // Supervisor is captured at creation → the next onboarding gap is IA school
  // assignment (the activation engine in Phase 2 computes this authoritatively).
  const status: StaffStatus = supervisorId ? "PendingSchoolAssignment" : "PendingSupervisor";

  const staffId = `STF-NEW-${String(++staffSeq).padStart(3, "0")}`;
  const row: OrgStaff = {
    staffId,
    name: input.name.trim(),
    role,
    region: input.region?.trim() || undefined,
    district: input.district?.trim() || undefined,
    supervisorId,
    email: input.email.trim().toLowerCase(),
    jobTitle: input.jobTitle?.trim() || undefined,
    status,
    createdBy: user.name,
    createdAt: new Date().toISOString().slice(0, 10),
  };
  addOrgStaff(row);

  emitAudit({
    action: "staff.created",
    subjectKind: "Staff",
    subjectId: staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { name: row.name, role, email: row.email, supervisorId, status },
  });

  // The next owner of this onboarding is IA (assign schools) + the supervisor.
  const supervisorName = supervisorId ? orgStaff(supervisorId)?.name : undefined;
  emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
    template: "staff.created.assignSchools",
    channel: "Inbox",
    title: `New ${role} added — assign schools to activate planning`,
    body: `${row.name} was added by ${user.name}. Assign schools so their planning scope, targets, and dashboard activate.`,
    href: "/admin/users",
  });

  emitAudit({
    action: "staff.supervisorAssignedAtCreate",
    subjectKind: "Staff",
    subjectId: staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { supervisorId, supervisorName, role: supervisorId ? supervisorRoleFor(role) : undefined },
  });

  revalidatePath("/admin/users");
  // Newly-created staff may be Active immediately (CCEO with supervisor
  // + targets handed over in one drawer). Refresh /planning so the
  // assignment drawers offer them without a reload.
  revalidatePath("/planning");
  return { ok: true, id: staffId, status };
}

// ─── setPrimaryDistrict (Phase 5 — clears the primary-district gate) ──
//
// The home/base district (no accommodation). Setting it auto-classifies every
// other assigned district as secondary and unblocks budget calculation. Settable
// by CD / HR / Admin or the staff member themselves.

export type SetPrimaryDistrictResult =
  | { ok: false; reason: "FORBIDDEN" | "STAFF_NOT_FOUND" | "INVALID_INPUT" }
  | { ok: true; staffId: string };

export async function setPrimaryDistrict(staffId: string, districtId: string): Promise<SetPrimaryDistrictResult> {
  const user = await getCurrentUser();
  const isSelf = user.staffId === staffId;
  if (!STAFF_ADMIN_ROLES.has(user.role) && !isSelf) return { ok: false, reason: "FORBIDDEN" };
  if (!districtId?.trim()) return { ok: false, reason: "INVALID_INPUT" };

  const staff = setStaffPrimaryDistrict(staffId, districtId.trim());
  if (!staff) return { ok: false, reason: "STAFF_NOT_FOUND" };

  emitAudit({
    action: "staff.primaryDistrictSet",
    subjectKind: "Staff",
    subjectId: staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { staffName: staff.name, primaryDistrictId: districtId.trim() },
  });
  revalidatePath("/admin/users");
  revalidatePath("/planning");
  return { ok: true, staffId };
}

// ─── assignTargetProfile (Phase 6 — final gate → Active) ─────────────
//
// A Program Lead (or CD/HR/Admin) assigns + approves the staff member's FY
// target profile. This is the last onboarding prerequisite; once set, the
// activation engine flips the staff to Active.

const TARGET_APPROVER_ROLES = new Set<string>(["CountryProgramLead", "CountryDirector", "HumanResource", "Admin"]);

export type AssignTargetResult =
  | { ok: false; reason: "FORBIDDEN" | "STAFF_NOT_FOUND" | "INVALID_INPUT" }
  | { ok: true; staffId: string; activated: boolean };

export async function assignTargetProfile(
  staffId: string,
  input: { fy: string; visitTarget: number; trainingTarget?: number; ssaTarget?: number; clusterMeetingTarget?: number; partnerMonitoringTarget?: number },
): Promise<AssignTargetResult> {
  const user = await getCurrentUser();
  if (!TARGET_APPROVER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const staff = orgStaff(staffId);
  if (!staff) return { ok: false, reason: "STAFF_NOT_FOUND" };
  if (!input.fy?.trim() || !Number.isFinite(input.visitTarget) || input.visitTarget <= 0) {
    return { ok: false, reason: "INVALID_INPUT" };
  }

  addStaffTargetProfile({
    staffId,
    role: staff.role,
    fy: input.fy.trim(),
    visitTarget: input.visitTarget,
    trainingTarget: input.trainingTarget,
    ssaTarget: input.ssaTarget,
    clusterMeetingTarget: input.clusterMeetingTarget,
    partnerMonitoringTarget: input.partnerMonitoringTarget,
    approvedBy: user.name,
    isActive: true,
  });

  const activated = canActivateStaff(staffId);

  emitAudit({
    action: "staff.targetProfileAssigned",
    subjectKind: "Staff",
    subjectId: staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { staffName: staff.name, fy: input.fy, visitTarget: input.visitTarget, approvedBy: user.name, activated },
  });
  if (activated) {
    emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
      template: "staff.activated",
      channel: "Inbox",
      title: `${staff.name} is now active`,
      body: `${staff.name} (${staff.role}) completed onboarding — planning scope, targets, dashboard, and filters are live.`,
      href: "/admin/users",
    });
  }

  revalidatePath("/admin/users");
  // Phase 6 activation makes the staff appear in assignment drawers
  // (PL → supervised CCEO, capacity overlays). Refresh /planning so PLs
  // can route to them in the same session.
  if (activated) revalidatePath("/planning");
  return { ok: true, staffId, activated };
}

// ─── assignSupervisor (Phase 3 — standalone re-assignment + audit/history) ──
//
// Supervisor is captured at creation; this changes it later (transfer, workload
// balancing, restructuring). CD / RVP / HR / Admin only. The new supervisor must
// hold the role one step up the chain. Audit captures old→new + reason so the
// supervision-change history is reconstructable from the audit log.

const SUPERVISOR_ASSIGN_ROLES = new Set<string>(["CountryDirector", "RVP", "HumanResource", "Admin"]);

export type AssignSupervisorResult =
  | { ok: false; reason: "FORBIDDEN" | "STAFF_NOT_FOUND" | "INVALID_INPUT" | "WRONG_LEVEL" }
  | { ok: true; staffId: string };

export async function assignSupervisor(
  input: { staffId: string; newSupervisorId: string; reason: string; effectiveDate?: string },
): Promise<AssignSupervisorResult> {
  const user = await getCurrentUser();
  if (!SUPERVISOR_ASSIGN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const staff = orgStaff(input.staffId);
  if (!staff) return { ok: false, reason: "STAFF_NOT_FOUND" };
  if (!input.newSupervisorId?.trim() || !input.reason?.trim() || input.reason.trim().length < 4) {
    return { ok: false, reason: "INVALID_INPUT" };
  }

  const needed = supervisorRoleFor(staff.role);
  const candidate = orgStaff(input.newSupervisorId);
  if (!candidate || (needed && candidate.role !== needed)) return { ok: false, reason: "WRONG_LEVEL" };

  const oldSupervisorId = staff.supervisorId;
  setStaffSupervisor(input.staffId, input.newSupervisorId);

  emitAudit({
    action: "staffSupervision.assigned",
    subjectKind: "StaffSupervision",
    subjectId: input.staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      staffName: staff.name,
      oldSupervisorId,
      oldSupervisorName: oldSupervisorId ? orgStaff(oldSupervisorId)?.name : undefined,
      newSupervisorId: input.newSupervisorId,
      newSupervisorName: candidate.name,
      reason: input.reason.trim(),
      effectiveDate: input.effectiveDate ?? new Date().toISOString().slice(0, 10),
    },
  });
  // Notify the staff + both supervisors.
  emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
    template: "staffSupervision.changed",
    channel: "Inbox",
    title: `${staff.name} reassigned to ${candidate.name}`,
    body: `${user.name} reassigned ${staff.name} (${labelForRole(staff.role)}) to ${candidate.name}. Reason: ${input.reason.trim()}.`,
    href: "/admin/users",
  });

  revalidatePath("/admin/users");
  return { ok: true, staffId: input.staffId };
}
