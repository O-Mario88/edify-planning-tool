// Per-role filter visibility matrix.
//
// The 10 filter slots aren't shown identically to every role — HR has no
// reason to filter by Partner, RVP isn't granted partner access in the
// access model, CCEOs are locked to their own scope. This matrix is the
// single source of truth — the bar reads it through getFilterScope.

import type { EdifyRole } from "@/lib/auth-public";
import type { FilterKey, VisibilityMatrix } from "./types";

// Full visibility for the widest-scope roles (CD, Admin).
const FULL: Record<FilterKey, boolean> = {
  fy: true,
  quarter: true,
  region: true,
  district: true,
  cluster: true,
  cceo: true,
  partner: true,
  package: true,
  ssa: true,
  champion: true,
};

export const FILTER_VISIBILITY: VisibilityMatrix = {
  // CCEO is locked to their own portfolio — `cceo` slot is rendered but
  // returns the user themselves as the only option (handled in the
  // scope service); they get the rest of the bar so they can slice
  // their own work across geography / package / status.
  CCEO: { ...FULL },

  CountryProgramLead: { ...FULL },
  CountryDirector:    { ...FULL },
  Admin:              { ...FULL },

  // RVP — per spec, no partner access in the standard access model.
  // The slot is hidden until a contract-specific exception is wired.
  RVP: { ...FULL, partner: false },

  // Impact Assessment — sees partners only when the partner is in the
  // verification scope. For slice 1 we show it; later slices will
  // narrow to partners with active evidence pipelines.
  ImpactAssessment: { ...FULL },

  // Accountant — sees partners only when there's a financial linkage.
  // Cluster / Champion filtering aren't useful for the cost surface,
  // but the slots stay visible so finance can cross-reference.
  ProgramAccountant: { ...FULL },

  // HR — no partner scope at all. Champion isn't an HR concern but the
  // slot is harmless to keep visible.
  HumanResource: { ...FULL, partner: false },

  // Project Coordinator — full slice bar across projects, schools,
  // geography, partners (partners deliver project activities).
  ProjectCoordinator: { ...FULL },

  // Partner roles — see only their own org. The Partner filter slot
  // resolves to the user's partner organisation (single option), and
  // CCEO is hidden because partners don't filter by staff CCEO.
  PartnerAdmin:        { ...FULL, cceo: false },
  PartnerFieldOfficer: { ...FULL, cceo: false },
  PartnerViewer:       { ...FULL, cceo: false },
};

// Convenience accessor — `visibilityFor("CCEO").partner` → boolean.
export function visibilityFor(role: EdifyRole): Record<FilterKey, boolean> {
  return FILTER_VISIBILITY[role] ?? FULL;
}
