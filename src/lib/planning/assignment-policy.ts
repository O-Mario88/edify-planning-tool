// AssignmentPolicyService — the single source of truth for "who can this
// activity be assigned to?" Encodes the role rules + staff support capacity so
// every assignment surface (schedule drawers, plan-action, APIs) uses the SAME
// decision instead of re-implementing it. Pure given its inputs; capacity is
// computed from the store.
//
// Role rules:
//   • CCEO  → self or partner (own portfolio only).
//   • PL    → self (only for PL-owned schools) · supervised CCEOs · partner
//             (only for PL-owned schools, or with an explicit override).
//   • Others can't self-assign field support.
// Capacity: a staff member directly supports at most N UNIQUE schools per FY
// (set by CD/IA). Once full, self-assignment to a NEW school is blocked and
// partner assignment becomes the route. A school already supported doesn't
// re-count, so additional activities for it stay allowed.

import { activities } from "@/lib/actions/store";

export const STAFF_SUPPORT_LIMIT_DEFAULT = 50;

// CD/IA-set per-staff limits (demo config — production: StaffSupportCapacity
// table set by CD/IA). Keyed by staffId. A low value here demonstrates the
// at-limit behaviour for that staff.
const STAFF_LIMITS: Record<string, number> = {
  "STF-PC-001": 3, // Paul Chinyama (demo CCEO) — small limit to exercise the gate
};

export function staffSupportLimit(staffId: string): number {
  return STAFF_LIMITS[staffId] ?? STAFF_SUPPORT_LIMIT_DEFAULT;
}

// Staff-delivered, school-level support that counts toward the direct limit.
// (Partner-delivered activities never count — they're partner-supported.)
const CAPACITY_COUNTED_KINDS = new Set([
  "SCHOOL_VISIT", "IN_SCHOOL_COACHING", "SSA_FOLLOW_UP", "LESSON_OBSERVATION",
  "COURTESY_VISIT", "PARTNER_FOLLOW_UP", "TRAINING_FOLLOW_UP",
]);
const EXCLUDED_STATUS = new Set(["Cancelled", "Rejected", "Returned", "Deferred"]);

export type StaffCapacity = {
  max: number;
  used: number;
  remaining: number;
  atLimit: boolean;
  nearLimit: boolean; // ≥90% used
};

/** Unique schools this staff directly supports (staff-delivered, counted kinds). */
export function computeStaffCapacity(staffId: string): StaffCapacity {
  const schools = new Set(
    activities()
      .filter((a) =>
        a.assigneeId === staffId &&
        a.deliveryType !== "partner" &&
        !EXCLUDED_STATUS.has(a.status) &&
        CAPACITY_COUNTED_KINDS.has(a.kind) &&
        a.schoolId,
      )
      .map((a) => a.schoolId as string),
  );
  const max = staffSupportLimit(staffId);
  const used = schools.size;
  return {
    max, used,
    remaining: Math.max(0, max - used),
    atLimit: used >= max,
    nearLimit: max > 0 && used / max >= 0.9 && used < max,
  };
}

/** Does the staff already directly support this school this FY? (doesn't re-count) */
export function staffAlreadySupportsSchool(staffId: string, schoolId: string): boolean {
  return activities().some(
    (a) => a.assigneeId === staffId && a.schoolId === schoolId &&
      a.deliveryType !== "partner" && !EXCLUDED_STATUS.has(a.status) &&
      CAPACITY_COUNTED_KINDS.has(a.kind),
  );
}

// ── Decision engine ─────────────────────────────────────────────────

export type AssignmentOption = {
  type: "self" | "staff" | "partner";
  label: string;
  enabled: boolean;
  reason?: string;
  staffId?: string; // for type: "staff" (a supervised CCEO)
};

export type AssignmentInput = {
  role: string;
  isDirectOwner: boolean; // assigner owns / is directly responsible for the school
  isSupervisedSchool: boolean; // school owned by a CCEO the PL supervises
  schoolAlreadySupported: boolean;
  capacity: StaffCapacity;
  partnerAvailable: boolean;
  supervisedCceos?: { staffId: string; name: string }[];
  overrideGranted?: boolean; // ASSIGN_PARTNER_FOR_TEAM_SCHOOL_OVERRIDE
};

export function canAssignToSelf(i: AssignmentInput): { allowed: boolean; reason?: string } {
  const isCCEO = i.role === "CCEO";
  const isPL = i.role === "CountryProgramLead";
  if (!isCCEO && !isPL) return { allowed: false, reason: "Your role does not deliver direct school support." };
  if (isPL && !i.isDirectOwner) {
    return { allowed: false, reason: "You can only self-assign for schools you directly own. Assign to the responsible CCEO." };
  }
  // Capacity: a NEW school when at limit is blocked.
  if (!i.schoolAlreadySupported && i.capacity.remaining <= 0) {
    return { allowed: false, reason: `Direct support limit reached (${i.capacity.max} schools). Assign this to a partner.` };
  }
  return { allowed: true };
}

export function canAssignToPartner(i: AssignmentInput): { allowed: boolean; reason?: string } {
  const isCCEO = i.role === "CCEO";
  const isPL = i.role === "CountryProgramLead";
  if (isCCEO) return { allowed: true }; // own portfolio
  if (isPL) {
    if (i.isDirectOwner || i.overrideGranted) return { allowed: true };
    return { allowed: false, reason: "This school belongs to a CCEO you supervise. Assign to the responsible CCEO, or request a partner-assignment override." };
  }
  return { allowed: false, reason: "Your role cannot assign partner work." };
}

/** The full set of valid assignment options for this context (spec §8). */
export function getAssignmentOptions(i: AssignmentInput): AssignmentOption[] {
  const opts: AssignmentOption[] = [];
  const self = canAssignToSelf(i);
  // Only surface "self" for roles that can ever self-assign (CCEO, or PL-owned).
  if (i.role === "CCEO" || (i.role === "CountryProgramLead" && i.isDirectOwner)) {
    opts.push({ type: "self", label: "Assign to Myself", enabled: self.allowed, reason: self.reason });
  }
  // PL → supervised CCEOs for team schools.
  if (i.role === "CountryProgramLead" && i.isSupervisedSchool) {
    for (const c of i.supervisedCceos ?? []) {
      opts.push({ type: "staff", label: `Assign to ${c.name}`, enabled: true, staffId: c.staffId });
    }
  }
  // Partner.
  if (i.partnerAvailable) {
    const p = canAssignToPartner(i);
    opts.push({ type: "partner", label: "Assign to Partner", enabled: p.allowed, reason: p.reason });
  }
  return opts;
}
