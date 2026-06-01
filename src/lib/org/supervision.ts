// Org supervision — the canonical reporting chain.
//
// Staff identities themselves come from elsewhere (the login roster + the
// "Account Owner" on onboarded schools). What lived nowhere until now is who
// reports to whom. This module is that single source of truth:
//
//   CCEO                              → Program Lead
//   Program Lead / IA / Accountant    → Country Director
//   Country Director / HR             → RVP
//   RVP / Admin                       → (top of chain)
//
// Pure & client-safe (type-only import of EdifyRole) so dashboards, the team
// rollups, and the planner can all scope by the same chain.

import type { EdifyRole } from "@/lib/auth";

export type OrgStaff = {
  staffId: string;
  name: string;
  role: EdifyRole;
  region?: string;
  /** Direct supervisor's staffId, or null at the top of the chain. */
  supervisorId: string | null;
};

/** Which role a given role reports up to. Drives validation of assignments. */
export const SUPERVISOR_ROLE: Partial<Record<EdifyRole, EdifyRole>> = {
  CCEO: "CountryProgramLead",
  CountryProgramLead: "CountryDirector",
  ImpactAssessment: "CountryDirector",
  ProgramAccountant: "CountryDirector",
  CountryDirector: "RVP",
  HumanResource: "RVP",
};

export function supervisorRoleFor(role: EdifyRole): EdifyRole | undefined {
  return SUPERVISOR_ROLE[role];
}

// ────────── Canonical roster + assignments ──────────
//
// Reconciles the demo identities (login roster + the CCEO performance seed)
// into one tree with real staffId references. Year-2 reads this from the
// StaffSupervision table.

export const ORG_STAFF: OrgStaff[] = [
  // Top of chain
  { staffId: "STF-EW-003", name: "Esther Wanjiru", role: "RVP",              region: "All",     supervisorId: null },
  // Report to RVP
  { staffId: "STF-SO-007", name: "Sarah Okello",   role: "CountryDirector",  region: "All",     supervisorId: "STF-EW-003" },
  { staffId: "STF-AW-019", name: "Anne Wairimu",   role: "HumanResource",    region: "All",     supervisorId: "STF-EW-003" },
  // Report to Country Director
  { staffId: "STF-DM-014", name: "Daniel Mwangi",  role: "CountryProgramLead", region: "Central", supervisorId: "STF-SO-007" },
  { staffId: "STF-AD-021", name: "Aisha Dar",      role: "CountryProgramLead", region: "North",   supervisorId: "STF-SO-007" },
  { staffId: "STF-GA-042", name: "Grace Alimo",    role: "ImpactAssessment", region: "All",     supervisorId: "STF-SO-007" },
  { staffId: "STF-MT-031", name: "Moses Tindi",    role: "ProgramAccountant", region: "All",     supervisorId: "STF-SO-007" },
  // CCEOs report to a Program Lead
  { staffId: "STF-PC-001", name: "Paul Chinyama",  role: "CCEO", region: "Central", supervisorId: "STF-DM-014" },
  { staffId: "STF-GN-007", name: "Grace Njeri",    role: "CCEO", region: "East",    supervisorId: "STF-DM-014" },
  { staffId: "STF-JO-022", name: "James Otieno",   role: "CCEO", region: "Central", supervisorId: "STF-DM-014" },
  { staffId: "STF-PM-031", name: "Purity Muthoni", role: "CCEO", region: "West",    supervisorId: "STF-DM-014" },
  { staffId: "STF-AH-044", name: "Abdi Hassan",    role: "CCEO", region: "North",   supervisorId: "STF-AD-021" },
  { staffId: "STF-PM-052", name: "Peter Mutua",    role: "CCEO", region: "East",    supervisorId: "STF-AD-021" },
];

const BY_ID = new Map(ORG_STAFF.map((s) => [s.staffId, s]));

export function orgStaff(staffId: string): OrgStaff | undefined {
  return BY_ID.get(staffId);
}

export function supervisorOf(staffId: string): OrgStaff | undefined {
  const sid = BY_ID.get(staffId)?.supervisorId;
  return sid ? BY_ID.get(sid) : undefined;
}

/** Direct reports of a supervisor (one level down). */
export function directReportsOf(supervisorId: string): OrgStaff[] {
  return ORG_STAFF.filter((s) => s.supervisorId === supervisorId);
}

/** Direct reports that are CCEOs — a Program Lead's portfolio of officers. */
export function cceosSupervisedBy(plStaffId: string): OrgStaff[] {
  return directReportsOf(plStaffId).filter((s) => s.role === "CCEO");
}

/** Everyone below `staffId` in the tree (transitive) — for CD / RVP rollups. */
export function subtreeOf(staffId: string): OrgStaff[] {
  const out: OrgStaff[] = [];
  const walk = (id: string) => {
    for (const r of directReportsOf(id)) { out.push(r); walk(r.staffId); }
  };
  walk(staffId);
  return out;
}

/** The chain of supervisors above `staffId`, nearest first. */
export function chainAbove(staffId: string): OrgStaff[] {
  const out: OrgStaff[] = [];
  let cur = supervisorOf(staffId);
  while (cur) { out.push(cur); cur = supervisorOf(cur.staffId); }
  return out;
}

/**
 * The set of staffIds a user can see, by role:
 *   RVP / Admin / CD → everyone in their subtree (CD/RVP) or all (Admin)
 *   Program Lead     → their supervised CCEOs (+ self)
 *   everyone else    → just themselves
 */
export function visibleStaffIds(staffId: string, role: EdifyRole): Set<string> {
  if (role === "Admin") return new Set(ORG_STAFF.map((s) => s.staffId));
  const ids = new Set<string>([staffId]);
  for (const s of subtreeOf(staffId)) ids.add(s.staffId);
  return ids;
}
