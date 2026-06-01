// Target profile is the final activation gate → staff becomes Active.

import { describe, expect, it } from "vitest";
import { addOrgStaff, setStaffPrimaryDistrict } from "@/lib/org/supervision";
import { addIntakeSchool, assignSchoolToCceo } from "@/lib/intake/intake-mock";
import { computeActivationReadiness } from "@/lib/org/staff-activation";
import { addStaffTargetProfile, defaultTargetProfileFor, hasTargetProfile } from "@/lib/targets/staff-target-profile";

describe("defaultTargetProfileFor", () => {
  it("uses the role default (CCEO 560 / PL 280)", () => {
    expect(defaultTargetProfileFor("X", "CCEO", "2026").visitTarget).toBe(560);
    expect(defaultTargetProfileFor("X", "CountryProgramLead", "2026").visitTarget).toBe(280);
  });
});

describe("final gate → Active", () => {
  addOrgStaff({
    staffId: "STF-TP-CCEO", name: "Target Profile Cceo", role: "CCEO", region: "Central",
    supervisorId: "STF-DM-014", email: "tp.cceo@edify.org", createdBy: "Sarah Okello",
    primaryDistrictId: "Wakiso",
  });
  addIntakeSchool({
    schoolId: "72001", schoolName: "TP School", region: "Central Region", district: "Wakiso",
    schoolType: "Client", dateAdded: "2026-06-02", addedBy: "Grace Alimo",
  });
  assignSchoolToCceo("72001", "Target Profile Cceo");

  it("with everything but a target profile → PendingTargetProfile (3/4)", () => {
    const r = computeActivationReadiness("STF-TP-CCEO");
    expect(r.status).toBe("PendingTargetProfile");
    expect(r.metCount).toBe(3);
  });

  it("assigning an active target profile → Active (4/4)", () => {
    addStaffTargetProfile({ staffId: "STF-TP-CCEO", role: "CCEO", fy: "2026", visitTarget: 560, approvedBy: "Daniel Mwangi", isActive: true });
    expect(hasTargetProfile("STF-TP-CCEO")).toBe(true);
    const r = computeActivationReadiness("STF-TP-CCEO");
    expect(r.status).toBe("Active");
    expect(r.metCount).toBe(4);
    expect(r.gaps).toHaveLength(0);
  });
});

// Guard: setStaffPrimaryDistrict round-trips (used by the chain above).
describe("primary district round-trip", () => {
  it("set then read", () => {
    addOrgStaff({ staffId: "STF-RT-1", name: "RT One", role: "CCEO", supervisorId: "STF-DM-014", email: "rt1@edify.org", createdBy: "x" });
    setStaffPrimaryDistrict("STF-RT-1", "Gulu");
    // primaryDistrict requirement now met for that staff (schools still missing).
    expect(computeActivationReadiness("STF-RT-1").met.primaryDistrict).toBe(true);
  });
});
