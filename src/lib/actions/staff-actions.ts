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
  supervisorRoleFor,
  type OrgStaff,
  type StaffStatus,
} from "@/lib/org/supervision";
import { validateNewStaff, type NewStaffInput } from "@/lib/intake/staff-creation-core";
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
