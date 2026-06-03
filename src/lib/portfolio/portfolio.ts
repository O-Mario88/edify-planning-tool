// School portfolio engine — the truth layer behind "whose schools are these".
//
// Core product rule (the spine of the whole workflow):
//   School ownership stays with the registered account owner. When a school is
//   uploaded with an Account Owner who is a registered staff member, the school
//   AUTOMATICALLY appears in that owner's portfolio — dashboard, planning,
//   analytics, and counts — with no extra step. Partner assignment only
//   delegates execution; it never removes a school from the owner's portfolio.
//
// Ownership source of truth = intakeSchools.assignedCceo (a name), resolved to a
// staffId via the supervision roster (staffIdByName). When the name does NOT
// resolve to a registered staff member, the school is "unmatched" and surfaces
// in the IA owner-mapping queue instead of silently disappearing.
//
// Pure & client-safe so dashboards, the staff portfolio view, and the IA queues
// all compute from the same numbers.

import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import { orgStaff, staffIdByName, type OrgStaff } from "@/lib/org/supervision";
import { schoolIdsWithActivePartner } from "./partner-assignments";

// ── Owner resolution ───────────────────────────────────────────────

export type OwnerResolution =
  | { status: "matched"; staffId: string; name: string; staff: OrgStaff }
  | { status: "unmatched"; name: string }
  | { status: "none" };

/** Resolve a school's Account Owner name to a registered staff member. */
export function resolveOwner(assignedCceo?: string | null): OwnerResolution {
  const name = assignedCceo?.trim();
  if (!name) return { status: "none" };
  const staffId = staffIdByName(name);
  if (!staffId) return { status: "unmatched", name };
  const staff = orgStaff(staffId);
  if (!staff) return { status: "unmatched", name };
  return { status: "matched", staffId, name: staff.name, staff };
}

// ── Portfolio counts ───────────────────────────────────────────────

export type PortfolioCounts = {
  total: number;
  client: number;
  core: number;
  /** Schools still awaiting their first SSA (planning-locked). */
  missingSsa: number;
  /** Schools with at least one active partner delegation (still owned by staff). */
  partnerAssigned: number;
  /** Schools whose planning is open (first SSA done). */
  planningOpen: number;
  /** Schools assigned to a cluster (cluster gate cleared). */
  clustered: number;
  /** Schools still awaiting cluster assignment (next setup action). */
  unclustered: number;
};

function countSchools(schools: IntakeSchool[]): PortfolioCounts {
  const withPartner = schoolIdsWithActivePartner();
  let client = 0, core = 0, missingSsa = 0, partnerAssigned = 0, planningOpen = 0;
  let clustered = 0, unclustered = 0;
  for (const s of schools) {
    if (s.schoolType === "Client") client += 1;
    else if (s.schoolType === "Core") core += 1;
    if (s.ssaStatus === "SSA Not Done") missingSsa += 1;
    if (!s.planningLocked) planningOpen += 1;
    if (withPartner.has(s.schoolId)) partnerAssigned += 1;
    // Cluster status: absent rows are treated as unclustered.
    if (s.clusterStatus === "clustered") clustered += 1;
    else unclustered += 1;
  }
  return { total: schools.length, client, core, missingSsa, partnerAssigned, planningOpen, clustered, unclustered };
}

// ── Per-staff portfolio ────────────────────────────────────────────

export type StaffPortfolio = {
  staffId: string;
  staffName: string;
  schools: IntakeSchool[];
  counts: PortfolioCounts;
};

/** All schools auto-distributed to a staff member (resolved by owner name). */
export function portfolioForStaffId(staffId: string): StaffPortfolio {
  const staff = orgStaff(staffId);
  const schools = intakeSchools.filter((s) => {
    const r = resolveOwner(s.assignedCceo);
    return r.status === "matched" && r.staffId === staffId;
  });
  return {
    staffId,
    staffName: staff?.name ?? staffId,
    schools,
    counts: countSchools(schools),
  };
}

/** Portfolio looked up by owner name (convenience for name-keyed callers). */
export function portfolioForName(name: string): StaffPortfolio | undefined {
  const staffId = staffIdByName(name);
  return staffId ? portfolioForStaffId(staffId) : undefined;
}

// ── Owner distribution + unmatched (IA owner-mapping queue) ─────────

export type OwnerDistributionSummary = {
  /** Schools whose owner resolves to a registered staff member. */
  matched: number;
  /** Schools whose owner name does NOT resolve — need IA mapping. */
  unmatched: number;
  /** Schools with no owner set at all. */
  unassigned: number;
  /** Distinct registered owners holding ≥1 school. */
  owners: number;
};

export function ownerDistribution(): OwnerDistributionSummary {
  let matched = 0, unmatched = 0, unassigned = 0;
  const owners = new Set<string>();
  for (const s of intakeSchools) {
    const r = resolveOwner(s.assignedCceo);
    if (r.status === "matched") { matched += 1; owners.add(r.staffId); }
    else if (r.status === "unmatched") unmatched += 1;
    else unassigned += 1;
  }
  return { matched, unmatched, unassigned, owners: owners.size };
}

export type UnmatchedOwner = {
  /** The exact owner name as entered on upload (preserved for IA review). */
  name: string;
  schoolIds: string[];
  schools: IntakeSchool[];
  count: number;
};

/**
 * Schools whose Account Owner name was entered but does NOT resolve to a
 * registered staff member — grouped by the entered name for the IA queue.
 */
export function unmatchedOwners(): UnmatchedOwner[] {
  const groups = new Map<string, IntakeSchool[]>();
  for (const s of intakeSchools) {
    const r = resolveOwner(s.assignedCceo);
    if (r.status !== "unmatched") continue;
    const key = r.name;
    const arr = groups.get(key) ?? [];
    arr.push(s);
    groups.set(key, arr);
  }
  return [...groups.entries()]
    .map(([name, schools]) => ({
      name,
      schools,
      schoolIds: schools.map((s) => s.schoolId),
      count: schools.length,
    }))
    .sort((a, b) => b.count - a.count);
}

/** Schools with no owner at all (also IA's responsibility to assign). */
export function unassignedSchools(): IntakeSchool[] {
  return intakeSchools.filter((s) => resolveOwner(s.assignedCceo).status === "none");
}
