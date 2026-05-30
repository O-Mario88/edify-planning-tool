// Reschedule notification routing (spec section 4).
//
// Staff reschedule → PL + IA + Accountant + HR (CD when urgent/repeat)
// Partner reschedule → CCEO + PL + CD + IA + Accountant + RVP
//
// `reviewerRoleUserIds(actor, region)` flattens the role set through
// the directory so the system-message emit gets concrete userIds.
// Mocked today — real query lands when the users table does.

import type { EdifyRole } from "@/lib/auth-public";
import type { RescheduleActor } from "./types";

// Mock directory of reviewer userIds by role. Mirrors the seed users
// in lib/messages-v2/directory; production swaps for a real query
// filtered by region / scope.
const REVIEWERS_BY_ROLE: Record<string, string[]> = {
  HumanResource:      ["STF-AW-019"], // Anne Wairimu
  CountryDirector:    ["STF-SO-007"], // Sarah Okello
  CountryProgramLead: ["STF-DM-001"], // Daniel Mwangi
  CCEO:               ["STF-PC-001", "STF-SN-101", "STF-IM-005"],
  ImpactAssessment:   ["STF-GA-042"], // Grace Alimo
  ProgramAccountant:  ["STF-MT-006"], // Moses Tindi
  RVP:                ["STF-EW-003"], // Esther Wanjiru
};

export type RescheduleRecipientPlan = {
  /** Reviewer roles to notify. Drives the routing chip strip on the
   *  drawer and the per-recipient delivery records. */
  roles:    EdifyRole[];
  /** Directory user-ids — flattened from `roles`. */
  userIds:  string[];
};

export function reviewerPlan(actor: RescheduleActor, opts?: { urgent?: boolean; repeated?: boolean }): RescheduleRecipientPlan {
  if (actor === "staff") {
    const roles: EdifyRole[] = ["CountryProgramLead", "ImpactAssessment", "ProgramAccountant", "HumanResource"];
    // Optional: CD on urgent / repeated reschedule (spec section 4).
    if (opts?.urgent || opts?.repeated) roles.push("CountryDirector");
    return { roles, userIds: flatten(roles) };
  }
  // Partner reschedules go further up the chain.
  const roles: EdifyRole[] = [
    "CCEO",
    "CountryProgramLead",
    "CountryDirector",
    "ImpactAssessment",
    "ProgramAccountant",
    "RVP",
  ];
  return { roles, userIds: flatten(roles) };
}

function flatten(roles: EdifyRole[]): string[] {
  const ids = new Set<string>();
  for (const r of roles) {
    for (const uid of REVIEWERS_BY_ROLE[r] ?? []) ids.add(uid);
  }
  return [...ids];
}

// Human-friendly label for the routing chips in the drawer.
export const ROLE_CHIP_LABEL: Record<EdifyRole, string> = {
  CCEO:               "CCEO",
  CountryProgramLead: "PL",
  CountryDirector:    "CD",
  RVP:                "RVP",
  HumanResource:      "HR",
  ProgramAccountant:  "Finance",
  ImpactAssessment:   "Impact",
  PartnerAdmin:       "Partner",
  PartnerFieldOfficer:"Partner",
  PartnerViewer:      "Partner",
  Admin:              "Admin",
};
