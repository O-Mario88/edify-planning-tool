// Staff creation validation — required fields, unique email, supervisor chain.

import { describe, expect, it } from "vitest";
import { validateNewStaff, CREATABLE_STAFF_ROLES, type NewStaffInput } from "@/lib/intake/staff-creation-core";
import type { EdifyRole } from "@/lib/auth";

const taken = new Set(["paul.chinyama@edify.org"]);
// A supervisor-role resolver matching the demo org: Daniel/Aisha are PLs,
// Sarah is CD, Esther is RVP.
const roleById = (id: string): EdifyRole | undefined =>
  ({ "STF-DM-014": "CountryProgramLead", "STF-SO-007": "CountryDirector", "STF-EW-003": "RVP" } as Record<string, EdifyRole>)[id];

const base: NewStaffInput = {
  name: "Joyce Akinyi", email: "joyce.akinyi@edify.org", role: "CCEO",
  region: "Central", district: "Wakiso", supervisorStaffId: "STF-DM-014",
};

describe("validateNewStaff", () => {
  it("accepts a complete CCEO with a Program Lead supervisor", () => {
    expect(validateNewStaff(base, taken, roleById).ok).toBe(true);
  });
  it("requires name, email, role", () => {
    const r = validateNewStaff({ ...base, name: "", email: "", role: "" }, taken, roleById);
    expect(r.errors.name).toBeTruthy();
    expect(r.errors.email).toBeTruthy();
    expect(r.errors.role).toBeTruthy();
  });
  it("rejects a malformed or duplicate email", () => {
    expect(validateNewStaff({ ...base, email: "nope" }, taken, roleById).errors.email).toMatch(/valid/);
    expect(validateNewStaff({ ...base, email: "paul.chinyama@edify.org" }, taken, roleById).errors.email).toMatch(/already exists/);
  });
  it("requires region + district for field roles (CCEO/PL)", () => {
    const r = validateNewStaff({ ...base, region: "", district: "" }, taken, roleById);
    expect(r.errors.region).toBeTruthy();
    expect(r.errors.district).toBeTruthy();
  });
  it("requires a supervisor matching the reporting chain", () => {
    // No supervisor → required.
    expect(validateNewStaff({ ...base, supervisorStaffId: "" }, taken, roleById).errors.supervisorStaffId).toBeTruthy();
    // CCEO assigned a CD (wrong level) → rejected (must be a PL).
    expect(validateNewStaff({ ...base, supervisorStaffId: "STF-SO-007" }, taken, roleById).errors.supervisorStaffId).toMatch(/must be a Program Lead/);
  });
  it("an Accountant reports to a Country Director", () => {
    const r = validateNewStaff(
      { name: "Moses B", email: "moses.b@edify.org", role: "ProgramAccountant", supervisorStaffId: "STF-SO-007" },
      taken, roleById,
    );
    expect(r.ok).toBe(true);
  });
  it("CREATABLE roles include CCEO/PL/IA/Accountant/HR", () => {
    for (const r of ["CCEO", "CountryProgramLead", "ImpactAssessment", "ProgramAccountant", "HumanResource"]) {
      expect(CREATABLE_STAFF_ROLES).toContain(r);
    }
  });
});
