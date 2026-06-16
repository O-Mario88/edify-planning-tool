// Staff onboarding system-health summary.

import { describe, expect, it } from "vitest";
import { addOrgStaff } from "@/lib/org/supervision";
import { staffOnboardingHealth } from "@/lib/org/staff-health";

describe("staffOnboardingHealth", () => {
  it("counts created staff, pending activation, and missing-supervisor", () => {
    const before = staffOnboardingHealth();
    // A created CCEO with no supervisor → counts as pending + missing supervisor.
    addOrgStaff({
      staffId: "STF-HL-1", name: "Health One", role: "CCEO", region: "Central",
      supervisorId: null, email: "health.one@edify.org", createdBy: "Sarah Okello",
    });
    const after = staffOnboardingHealth();
    expect(after.totalCreated).toBe(before.totalCreated + 1);
    expect(after.pendingActivation).toBeGreaterThanOrEqual(before.pendingActivation + 1);
    expect(after.missingSupervisor).toBeGreaterThanOrEqual(before.missingSupervisor + 1);
  });
  it("flags a duplicate email against the demo roster", () => {
    addOrgStaff({
      staffId: "STF-HL-DUP", name: "Dup Email", role: "CCEO", supervisorId: "STF-DM-014",
      email: "cceo@edify.org", createdBy: "Sarah Okello", // collides with a demo-roster user
    });
    expect(staffOnboardingHealth().duplicateEmails).toContain("cceo@edify.org");
  });
});
