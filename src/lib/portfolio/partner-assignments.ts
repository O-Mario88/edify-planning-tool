// Partner activity assignments — EXECUTION delegation only.
//
// Core product rule: assigning a partner to a school delegates who *delivers*
// an activity. It NEVER changes who owns the school. Ownership stays with the
// registered account owner (intakeSchools.assignedCceo); the school stays in
// that owner's portfolio, counts, dashboard, planning, and analytics. A partner
// assignment is an additional row keyed by schoolId — surfaced as a delegation
// badge, counted in "partner-assigned", but never a transfer.
//
// Mutable, client-safe in-memory store (Year-1 mock; Year-2 = PartnerActivityAssignment table).

export type PartnerAssignmentStatus = "Active" | "Completed" | "Cancelled";

export type PartnerActivityAssignment = {
  id: string;
  schoolId: string;
  partnerName: string;
  /** Optional intervention area this delegation covers (free text for Year-1). */
  interventionArea?: string;
  note?: string;
  assignedByName: string;
  assignedByStaffId: string;
  assignedAt: string;
  status: PartnerAssignmentStatus;
};

// Seed: Soroti Faith Junior (40118) has one delegated partner so the
// "partner-assigned" portfolio count is non-zero in the demo.
export const partnerAssignments: PartnerActivityAssignment[] = [
  {
    id: "PA-0001",
    schoolId: "40118",
    partnerName: "Hope Education Partners",
    interventionArea: "Teaching Environment",
    note: "Delivers termly teacher coaching on behalf of the account owner.",
    assignedByName: "Aisha Dar",
    assignedByStaffId: "STF-AD-021",
    assignedAt: "2026-04-02",
    status: "Active",
  },
];

let seq = partnerAssignments.length;

export function addPartnerAssignment(input: {
  schoolId: string;
  partnerName: string;
  interventionArea?: string;
  note?: string;
  assignedByName: string;
  assignedByStaffId: string;
  assignedAt?: string;
}): PartnerActivityAssignment {
  seq += 1;
  const row: PartnerActivityAssignment = {
    id: `PA-${String(seq).padStart(4, "0")}`,
    schoolId: input.schoolId,
    partnerName: input.partnerName,
    interventionArea: input.interventionArea,
    note: input.note,
    assignedByName: input.assignedByName,
    assignedByStaffId: input.assignedByStaffId,
    assignedAt: input.assignedAt ?? new Date().toISOString().slice(0, 10),
    status: "Active",
  };
  partnerAssignments.unshift(row);
  return row;
}

export function setPartnerAssignmentStatus(id: string, status: PartnerAssignmentStatus): PartnerActivityAssignment | undefined {
  const row = partnerAssignments.find((p) => p.id === id);
  if (row) row.status = status;
  return row;
}

/** All assignments (any status) for a school. */
export function partnerAssignmentsForSchool(schoolId: string): PartnerActivityAssignment[] {
  return partnerAssignments.filter((p) => p.schoolId === schoolId);
}

/** Active delegations for a school. */
export function activePartnerAssignmentsForSchool(schoolId: string): PartnerActivityAssignment[] {
  return partnerAssignments.filter((p) => p.schoolId === schoolId && p.status === "Active");
}

/** Set of schoolIds with at least one ACTIVE partner delegation. */
export function schoolIdsWithActivePartner(): Set<string> {
  return new Set(partnerAssignments.filter((p) => p.status === "Active").map((p) => p.schoolId));
}
