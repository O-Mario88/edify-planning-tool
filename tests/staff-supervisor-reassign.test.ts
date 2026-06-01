// Supervisor re-assignment — chain validation + mutation.

import { describe, expect, it } from "vitest";
import { addOrgStaff, setStaffSupervisor, orgStaff, supervisorRoleFor } from "@/lib/org/supervision";

describe("supervisor mutation + chain rule", () => {
  addOrgStaff({
    staffId: "STF-SUP-CCEO", name: "Reassign Cceo", role: "CCEO", region: "Central",
    supervisorId: "STF-DM-014", email: "reassign.cceo@edify.org", createdBy: "Sarah Okello",
  });

  it("a CCEO reports to a Program Lead", () => {
    expect(supervisorRoleFor("CCEO")).toBe("CountryProgramLead");
  });

  it("setStaffSupervisor moves the CCEO to another Program Lead", () => {
    // STF-DM-014 (Daniel) → STF-AD-021 (Aisha), both PLs.
    expect(orgStaff("STF-AD-021")?.role).toBe("CountryProgramLead");
    setStaffSupervisor("STF-SUP-CCEO", "STF-AD-021");
    expect(orgStaff("STF-SUP-CCEO")?.supervisorId).toBe("STF-AD-021");
  });

  it("the candidate's role must match the chain (a CD is the wrong level for a CCEO)", () => {
    // STF-SO-007 (Sarah) is a Country Director — not a valid CCEO supervisor.
    const needed = supervisorRoleFor("CCEO");
    expect(orgStaff("STF-SO-007")?.role).not.toBe(needed);
  });
});
