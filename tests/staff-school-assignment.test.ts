// IA school assignment advances the activation engine (schools gate clears).

import { describe, expect, it } from "vitest";
import { addOrgStaff } from "@/lib/org/supervision";
import { addIntakeSchool, assignSchoolToCceo } from "@/lib/intake/intake-mock";
import { computeActivationReadiness } from "@/lib/org/staff-activation";

describe("assigning schools clears the school-assignment gate", () => {
  // A created CCEO with a supervisor but no schools.
  addOrgStaff({
    staffId: "STF-ASN-CCEO", name: "Assign Test Cceo", role: "CCEO", region: "Central",
    supervisorId: "STF-DM-014", email: "assign.cceo@edify.org", createdBy: "Sarah Okello",
  });
  // An onboarded school with no owner.
  addIntakeSchool({
    schoolId: "70001", schoolName: "Assign Test School", region: "Central Region", district: "Wakiso",
    schoolType: "Client", dateAdded: "2026-06-02", addedBy: "Grace Alimo",
  });

  it("before assignment → PendingSchoolAssignment (supervisor met, schools unmet)", () => {
    const r = computeActivationReadiness("STF-ASN-CCEO");
    expect(r.status).toBe("PendingSchoolAssignment");
    expect(r.met.schools).toBe(false);
    expect(r.metCount).toBe(1);
  });

  it("after IA assigns a school (sets assignedCceo) → schools gate clears, status advances", () => {
    assignSchoolToCceo("70001", "Assign Test Cceo");
    const r = computeActivationReadiness("STF-ASN-CCEO");
    expect(r.met.schools).toBe(true);
    expect(r.metCount).toBe(2); // supervisor + schools
    // Next unmet gate is primary district.
    expect(r.status).toBe("PendingPrimaryDistrict");
  });
});
