// Org supervision chain — CCEO→PL→CD→RVP.

import { describe, expect, it } from "vitest";
import {
  supervisorRoleFor,
  supervisorOf,
  directReportsOf,
  cceosSupervisedBy,
  subtreeOf,
  chainAbove,
  visibleStaffIds,
} from "@/lib/org/supervision";

describe("reports-to roles", () => {
  it("follows the chain CCEO→PL→CD→RVP (+ IA/Accountant/HR)", () => {
    expect(supervisorRoleFor("CCEO")).toBe("CountryProgramLead");
    expect(supervisorRoleFor("CountryProgramLead")).toBe("CountryDirector");
    expect(supervisorRoleFor("ImpactAssessment")).toBe("CountryDirector");
    expect(supervisorRoleFor("ProgramAccountant")).toBe("CountryDirector");
    expect(supervisorRoleFor("HumanResource")).toBe("RVP");
    expect(supervisorRoleFor("CountryDirector")).toBe("RVP");
    expect(supervisorRoleFor("RVP")).toBeUndefined();
  });
});

describe("assignments", () => {
  it("a CCEO's supervisor is a Program Lead", () => {
    expect(supervisorOf("STF-PC-001")?.staffId).toBe("STF-DM-014"); // Paul → Daniel
    expect(supervisorOf("STF-PC-001")?.role).toBe("CountryProgramLead");
  });
  it("Program Leads roll up to the Country Director, who rolls up to the RVP", () => {
    expect(supervisorOf("STF-DM-014")?.role).toBe("CountryDirector");
    expect(supervisorOf("STF-SO-007")?.role).toBe("RVP");
    expect(supervisorOf("STF-EW-003")).toBeUndefined(); // RVP at top
  });
  it("a Program Lead supervises a real set of CCEOs (not all)", () => {
    const daniel = cceosSupervisedBy("STF-DM-014").map((c) => c.staffId);
    const aisha = cceosSupervisedBy("STF-AD-021").map((c) => c.staffId);
    expect(daniel).toContain("STF-PC-001");
    expect(daniel).toContain("STF-GN-007");
    expect(aisha).toContain("STF-AH-044");
    // disjoint portfolios
    expect(daniel.some((id) => aisha.includes(id))).toBe(false);
  });
});

describe("rollups", () => {
  it("CD subtree includes both PLs and every CCEO under them", () => {
    const sub = subtreeOf("STF-SO-007").map((s) => s.staffId);
    expect(sub).toContain("STF-DM-014"); // PL
    expect(sub).toContain("STF-AD-021"); // PL
    expect(sub).toContain("STF-PC-001"); // a CCEO two levels down
    expect(sub).toContain("STF-GA-042"); // IA reports to CD
  });
  it("chainAbove walks up to the RVP", () => {
    const chain = chainAbove("STF-PC-001").map((s) => s.role);
    expect(chain).toEqual(["CountryProgramLead", "CountryDirector", "RVP"]);
  });
  it("visibleStaffIds: a PL sees self + supervised CCEOs; a CCEO sees only self", () => {
    const pl = visibleStaffIds("STF-DM-014", "CountryProgramLead");
    expect(pl.has("STF-DM-014")).toBe(true);
    expect(pl.has("STF-PC-001")).toBe(true);
    expect(pl.has("STF-AH-044")).toBe(false); // Aisha's CCEO, not Daniel's
    const cceo = visibleStaffIds("STF-PC-001", "CCEO");
    expect([...cceo]).toEqual(["STF-PC-001"]);
  });
});

describe("direct reports", () => {
  it("RVP's direct reports are the CD and HR", () => {
    const roles = directReportsOf("STF-EW-003").map((s) => s.role).sort();
    expect(roles).toEqual(["CountryDirector", "HumanResource"]);
  });
});
