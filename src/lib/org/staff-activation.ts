// Staff activation engine — THE SPINE of the onboarding workflow.
//
// CORE RULE: a staff member is Active only when every prerequisite their role
// needs is connected — account + role + supervisor + assigned schools +
// geography + primary district + target profile. This module computes that
// readiness in ONE place; every later phase (supervisor-assign, IA school
// assign, primary-district setup, target profile) writes the input it owns and
// re-runs this. Dashboards/auth read its output.
//
// Pure & client-safe.

import type { EdifyRole } from "@/lib/auth";
import { orgStaff, type StaffStatus } from "@/lib/org/supervision";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { getStaffProfile } from "@/lib/funds/budget/staff-district";
import { hasTargetProfile } from "@/lib/targets/staff-target-profile";

export type RequirementKey = "supervisor" | "schools" | "primaryDistrict" | "targetProfile";

// Per-role prerequisites, in lifecycle order. Roles not listed (RVP/Admin) have
// no onboarding gates. CD reports to RVP (supervisor only).
const REQUIREMENTS: Partial<Record<EdifyRole, RequirementKey[]>> = {
  CCEO: ["supervisor", "schools", "primaryDistrict", "targetProfile"],
  CountryProgramLead: ["supervisor", "primaryDistrict", "targetProfile"],
  ImpactAssessment: ["supervisor"],
  ProgramAccountant: ["supervisor"],
  HumanResource: ["supervisor"],
  CountryDirector: ["supervisor"],
};

// Which Pending* status an unmet requirement maps to.
const GATE_STATUS: Record<RequirementKey, StaffStatus> = {
  supervisor: "PendingSupervisor",
  schools: "PendingSchoolAssignment",
  primaryDistrict: "PendingPrimaryDistrict",
  targetProfile: "PendingTargetProfile",
};

const GATE_LABEL: Record<RequirementKey, string> = {
  supervisor: "Assign a supervisor",
  schools: "IA must assign schools",
  primaryDistrict: "Set the primary district",
  targetProfile: "Assign a target profile",
};

/** Count of onboarded schools whose Account Owner is this staff member. */
export function schoolsAssignedToName(name: string): number {
  const n = name.trim().toLowerCase();
  return intakeSchools.filter((s) => (s.assignedCceo ?? "").trim().toLowerCase() === n).length;
}

function requirementMet(key: RequirementKey, staffId: string, staffName: string): boolean {
  switch (key) {
    case "supervisor": return !!orgStaff(staffId)?.supervisorId;
    case "schools": return schoolsAssignedToName(staffName) > 0;
    case "primaryDistrict": return !!getStaffProfile(staffId)?.primaryDistrictId;
    case "targetProfile": return hasTargetProfile(staffId);
  }
}

export type ActivationReadiness = {
  staffId: string;
  role: EdifyRole;
  status: StaffStatus;
  /** Ordered unmet requirements (human-readable). */
  gaps: string[];
  /** Per-requirement met flags (only the role's requirements). */
  met: Partial<Record<RequirementKey, boolean>>;
  /** Total required vs met — for a progress bar. */
  requiredCount: number;
  metCount: number;
};

/**
 * Compute a staff member's onboarding readiness. The established seed roster
 * (no createdBy) is treated as Active; runtime-created staff are gated.
 */
export function computeActivationReadiness(staffId: string): ActivationReadiness {
  const staff = orgStaff(staffId);
  if (!staff) {
    return { staffId, role: "CCEO", status: "Inactive", gaps: ["Unknown staff"], met: {}, requiredCount: 0, metCount: 0 };
  }
  // Manual lifecycle states win over computed readiness.
  if (staff.status === "Suspended" || staff.status === "Inactive") {
    return { staffId, role: staff.role, status: staff.status, gaps: [], met: {}, requiredCount: 0, metCount: 0 };
  }
  // Established team (seeded, not created through the workflow) → Active.
  if (!staff.createdBy) {
    return { staffId, role: staff.role, status: "Active", gaps: [], met: {}, requiredCount: 0, metCount: 0 };
  }

  const reqs = REQUIREMENTS[staff.role] ?? [];
  const met: Partial<Record<RequirementKey, boolean>> = {};
  const gaps: string[] = [];
  let firstUnmet: RequirementKey | null = null;
  for (const key of reqs) {
    const ok = requirementMet(key, staffId, staff.name);
    met[key] = ok;
    if (!ok) {
      gaps.push(GATE_LABEL[key]);
      if (firstUnmet === null) firstUnmet = key;
    }
  }

  const metCount = reqs.filter((k) => met[k]).length;
  const status: StaffStatus = firstUnmet ? GATE_STATUS[firstUnmet] : "Active";
  return { staffId, role: staff.role, status, gaps, met, requiredCount: reqs.length, metCount };
}

export function canActivateStaff(staffId: string): boolean {
  return computeActivationReadiness(staffId).status === "Active";
}
