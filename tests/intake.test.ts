// Data-intake core — validation + FY/quarter derivation + role gate.

import { describe, expect, it } from "vitest";
import {
  DATA_INTAKE_ROLES,
  canIntakeData,
  SSA_INTERVENTION_AREAS,
  deriveFyFromDate,
  deriveQuarterFromDate,
  ssaAverage,
  validateNewSchool,
  validateSsaUpload,
  type SsaInterventionArea,
} from "@/lib/intake/intake-core";

describe("data-intake role gate (IA + Admin only — CD sets cost, not data)", () => {
  it("allows exactly Impact Assessment + Admin", () => {
    expect([...DATA_INTAKE_ROLES].sort()).toEqual(["Admin", "ImpactAssessment"]);
    expect(canIntakeData("ImpactAssessment")).toBe(true);
    expect(canIntakeData("Admin")).toBe(true);
  });
  it("excludes Country Director and everyone else", () => {
    for (const r of ["CountryDirector", "ProgramAccountant", "CCEO", "CountryProgramLead", "RVP"]) {
      expect(canIntakeData(r)).toBe(false);
    }
  });
});

describe("FY derivation (Oct 1 starts the next FY)", () => {
  it("Oct–Dec roll into the next FY", () => {
    expect(deriveFyFromDate("2025-10-01")).toBe("2026");
    expect(deriveFyFromDate("2025-12-31")).toBe("2026");
  });
  it("Jan–Sep stay in the current FY", () => {
    expect(deriveFyFromDate("2026-01-15")).toBe("2026");
    expect(deriveFyFromDate("2026-09-30")).toBe("2026");
  });
});

describe("quarter derivation (Q1 Oct-Dec … Q4 Jul-Sep)", () => {
  it("maps each band", () => {
    expect(deriveQuarterFromDate("2025-11-15")).toBe("Q1");
    expect(deriveQuarterFromDate("2026-02-01")).toBe("Q2");
    expect(deriveQuarterFromDate("2026-05-20")).toBe("Q3");
    expect(deriveQuarterFromDate("2026-08-09")).toBe("Q4");
  });
});

const fullScores = (v: number) =>
  Object.fromEntries(SSA_INTERVENTION_AREAS.map((a) => [a, v])) as Record<SsaInterventionArea, number>;

describe("ssaAverage", () => {
  it("averages the 8 areas to 1dp", () => {
    expect(ssaAverage(fullScores(8))).toBe(8);
    expect(ssaAverage({ ...fullScores(8), "Leadership Best Practice": 6 })).toBe(7.8);
    expect(ssaAverage({})).toBe(0);
  });
});

describe("validateNewSchool", () => {
  const existing = new Set(["32791"]);
  const base = { schoolId: "51230", schoolName: "X", region: "Central", district: "Wakiso", schoolType: "Client" as const };
  it("passes a complete unique submission", () => {
    expect(validateNewSchool(base, existing).ok).toBe(true);
  });
  it("flags a bad School ID format (must be digits)", () => {
    const r = validateNewSchool({ ...base, schoolId: "SCH-IA-9" }, existing);
    expect(r.ok).toBe(false);
    expect(r.errors.schoolId).toMatch(/digits/);
  });
  it("flags a duplicate id", () => {
    const r = validateNewSchool({ ...base, schoolId: "32791" }, existing);
    expect(r.ok).toBe(false);
    expect(r.errors.schoolId).toBeTruthy();
  });
  it("requires name, region, district", () => {
    const r = validateNewSchool({ ...base, schoolName: "", region: "", district: "" }, existing);
    expect(r.errors.schoolName).toBeTruthy();
    expect(r.errors.region).toBeTruthy();
    expect(r.errors.district).toBeTruthy();
  });
  it("rejects a non-numeric enrollment", () => {
    expect(validateNewSchool({ ...base, enrollment: "abc" }, existing).errors.enrollment).toBeTruthy();
    expect(validateNewSchool({ ...base, enrollment: "320" }, existing).ok).toBe(true);
  });
});

describe("validateSsaUpload", () => {
  const base = { schoolId: "SCH-IA-2001", ssaDate: "2026-02-01", scores: fullScores(7) };
  it("passes when all 8 scores are in 0–10 and a date is set", () => {
    expect(validateSsaUpload(base).ok).toBe(true);
  });
  it("requires a school and a date", () => {
    const r = validateSsaUpload({ ...base, schoolId: "", ssaDate: "" });
    expect(r.errors.schoolId).toBeTruthy();
    expect(r.errors.ssaDate).toBeTruthy();
  });
  it("requires every intervention score", () => {
    const r = validateSsaUpload({ ...base, scores: { "Leadership Best Practice": 5 } });
    expect(r.ok).toBe(false);
    expect(r.errors["Teaching Environment"]).toBeTruthy();
  });
  it("rejects scores outside 0–10", () => {
    expect(validateSsaUpload({ ...base, scores: { ...fullScores(7), "Leadership Best Practice": 11 } }).errors["Leadership Best Practice"]).toBeTruthy();
    expect(validateSsaUpload({ ...base, scores: { ...fullScores(7), "Leadership Best Practice": -1 } }).errors["Leadership Best Practice"]).toBeTruthy();
  });
});
