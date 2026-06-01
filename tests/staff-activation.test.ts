// Staff activation engine — the readiness/gating spine.

import { describe, expect, it } from "vitest";
import { addOrgStaff } from "@/lib/org/supervision";
import { computeActivationReadiness, canActivateStaff } from "@/lib/org/staff-activation";

describe("seed (established) staff", () => {
  it("are Active — they have no createdBy onboarding flag", () => {
    // Paul Chinyama (STF-PC-001) is a seeded CCEO.
    expect(computeActivationReadiness("STF-PC-001").status).toBe("Active");
    expect(canActivateStaff("STF-PC-001")).toBe(true);
  });
  it("RVP at the top is Active", () => {
    expect(computeActivationReadiness("STF-EW-003").status).toBe("Active");
  });
});

describe("a created CCEO walks the gates in order", () => {
  // Created via the workflow (createdBy set), supervisor assigned, no schools yet.
  addOrgStaff({
    staffId: "STF-TEST-CCEO", name: "Test Cceo Person", role: "CCEO", region: "Central",
    supervisorId: "STF-DM-014", email: "test.cceo@edify.org", createdBy: "Sarah Okello", createdAt: "2026-06-02",
    status: "PendingSchoolAssignment",
  });
  const r = computeActivationReadiness("STF-TEST-CCEO");
  it("with supervisor but no schools → PendingSchoolAssignment", () => {
    expect(r.status).toBe("PendingSchoolAssignment");
    expect(r.met.supervisor).toBe(true);
    expect(r.met.schools).toBe(false);
  });
  it("reports the ordered gaps + progress", () => {
    expect(r.gaps[0]).toMatch(/assign schools/i);
    expect(r.requiredCount).toBe(4); // supervisor, schools, primaryDistrict, targetProfile
    expect(r.metCount).toBe(1);      // only supervisor
    expect(canActivateStaff("STF-TEST-CCEO")).toBe(false);
  });
});

describe("a created staff with no supervisor", () => {
  addOrgStaff({
    staffId: "STF-TEST-NOSUP", name: "No Supervisor", role: "CCEO", region: "East",
    supervisorId: null, email: "nosup@edify.org", createdBy: "Anne Wairimu", createdAt: "2026-06-02",
  });
  it("→ PendingSupervisor (the first gate)", () => {
    const r = computeActivationReadiness("STF-TEST-NOSUP");
    expect(r.status).toBe("PendingSupervisor");
    expect(r.met.supervisor).toBe(false);
  });
});

describe("manual states win", () => {
  addOrgStaff({
    staffId: "STF-TEST-SUSP", name: "Suspended One", role: "CCEO", supervisorId: "STF-DM-014",
    email: "susp@edify.org", createdBy: "Sarah Okello", status: "Suspended",
  });
  it("a Suspended staff stays Suspended regardless of gaps", () => {
    expect(computeActivationReadiness("STF-TEST-SUSP").status).toBe("Suspended");
  });
});
