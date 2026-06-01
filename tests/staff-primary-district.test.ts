// Setting a primary district clears the next activation gate.

import { describe, expect, it } from "vitest";
import { addOrgStaff, setStaffPrimaryDistrict } from "@/lib/org/supervision";
import { addIntakeSchool, assignSchoolToCceo } from "@/lib/intake/intake-mock";
import { computeActivationReadiness } from "@/lib/org/staff-activation";

describe("primary-district gate", () => {
  // CCEO with supervisor + an assigned school, but no primary district yet.
  addOrgStaff({
    staffId: "STF-PD-CCEO", name: "Primary District Cceo", role: "CCEO", region: "Central",
    supervisorId: "STF-DM-014", email: "pd.cceo@edify.org", createdBy: "Sarah Okello",
  });
  addIntakeSchool({
    schoolId: "71001", schoolName: "PD Test School", region: "Central Region", district: "Wakiso",
    schoolType: "Client", dateAdded: "2026-06-02", addedBy: "Grace Alimo",
  });
  assignSchoolToCceo("71001", "Primary District Cceo");

  it("with schools but no primary district → PendingPrimaryDistrict (2/4)", () => {
    const r = computeActivationReadiness("STF-PD-CCEO");
    expect(r.status).toBe("PendingPrimaryDistrict");
    expect(r.met.primaryDistrict).toBe(false);
    expect(r.metCount).toBe(2);
  });

  it("after setting primary district → gate clears, advances to PendingTargetProfile (3/4)", () => {
    setStaffPrimaryDistrict("STF-PD-CCEO", "Wakiso");
    const r = computeActivationReadiness("STF-PD-CCEO");
    expect(r.met.primaryDistrict).toBe(true);
    expect(r.metCount).toBe(3);
    expect(r.status).toBe("PendingTargetProfile");
  });
});
