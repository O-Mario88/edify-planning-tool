// Staff onboarding system-health — the data-quality checks for the workflow.
//
// Surfaces the gaps the onboarding spec calls out: staff stuck in onboarding,
// staff without a supervisor, schools with no owner, duplicate emails. Pure &
// client-safe; reads the activation engine so it stays in lockstep with the
// real lifecycle.

import { createdOrgStaff, supervisorRoleFor, type StaffStatus } from "@/lib/org/supervision";
import { computeActivationReadiness } from "@/lib/org/staff-activation";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { DEMO_USERS } from "@/lib/auth-public";

export type StaffHealthReport = {
  totalCreated: number;
  active: number;
  pendingActivation: number;
  byStatus: Array<{ status: StaffStatus; count: number }>;
  missingSupervisor: number;
  unassignedSchools: number;
  duplicateEmails: string[];
};

export function staffOnboardingHealth(): StaffHealthReport {
  const created = createdOrgStaff();

  const statusCounts = new Map<StaffStatus, number>();
  let active = 0;
  let missingSupervisor = 0;
  for (const s of created) {
    const r = computeActivationReadiness(s.staffId);
    statusCounts.set(r.status, (statusCounts.get(r.status) ?? 0) + 1);
    if (r.status === "Active") active += 1;
    if (!s.supervisorId && supervisorRoleFor(s.role)) missingSupervisor += 1;
  }

  // Duplicate emails across the directory (created + demo roster).
  const seen = new Map<string, number>();
  for (const u of Object.values(DEMO_USERS)) {
    const e = u.email.trim().toLowerCase();
    seen.set(e, (seen.get(e) ?? 0) + 1);
  }
  for (const s of created) {
    if (!s.email) continue;
    const e = s.email.trim().toLowerCase();
    seen.set(e, (seen.get(e) ?? 0) + 1);
  }
  const duplicateEmails = [...seen.entries()].filter(([, n]) => n > 1).map(([e]) => e);

  const unassignedSchools = intakeSchools.filter((s) => !(s.assignedCceo ?? "").trim()).length;

  return {
    totalCreated: created.length,
    active,
    pendingActivation: created.length - active,
    byStatus: [...statusCounts.entries()].map(([status, count]) => ({ status, count })),
    missingSupervisor,
    unassignedSchools,
    duplicateEmails,
  };
}
