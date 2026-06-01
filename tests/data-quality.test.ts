// Data-quality auditor — integrity checks over the school universe.

import { describe, expect, it } from "vitest";
import { auditSchool, auditSchools, type QualitySchool } from "@/lib/intake/data-quality";

const known = (d: string) => ["Wakiso", "Kampala", "Gulu"].includes(d);

const clean: QualitySchool = {
  schoolId: "S-OK", schoolName: "Clean P/S", district: "Wakiso", region: "Central",
  enrollment: 300, assignedCceo: "Aisha Dar", ssaScores: [7, 8],
};

describe("auditSchool", () => {
  it("a complete school has zero issues", () => {
    expect(auditSchool(clean, known)).toEqual([]);
  });
  it("flags a missing region as an Error", () => {
    const r = auditSchool({ ...clean, region: undefined }, known);
    expect(r).toHaveLength(1);
    expect(r[0]).toMatchObject({ category: "Missing region", severity: "Error" });
  });
  it("flags an unknown district as an Error", () => {
    const r = auditSchool({ ...clean, district: "Atlantis" }, known);
    expect(r.some((i) => i.category === "Unknown district" && i.severity === "Error")).toBe(true);
  });
  it("flags missing/zero enrollment as a Warning", () => {
    expect(auditSchool({ ...clean, enrollment: 0 }, known)[0]).toMatchObject({ category: "Missing enrollment", severity: "Warning" });
    expect(auditSchool({ ...clean, enrollment: undefined }, known)[0].category).toBe("Missing enrollment");
  });
  it("flags an unassigned CCEO as a Warning", () => {
    expect(auditSchool({ ...clean, assignedCceo: "" }, known)[0]).toMatchObject({ category: "Unassigned CCEO", severity: "Warning" });
  });
  it("flags a never-assessed school as a Warning", () => {
    expect(auditSchool({ ...clean, ssaScores: [] }, known)[0]).toMatchObject({ category: "Never assessed", severity: "Warning" });
  });
  it("flags out-of-range SSA scores as an Error", () => {
    const r = auditSchool({ ...clean, ssaScores: [7, 11, -2] }, known);
    expect(r.some((i) => i.category === "SSA score out of range" && i.severity === "Error")).toBe(true);
  });
});

describe("auditSchools roll-up", () => {
  const report = auditSchools(
    [
      clean,
      { ...clean, schoolId: "S-NOREG", region: undefined },
      { ...clean, schoolId: "S-NOENR", enrollment: undefined },
    ],
    known,
  );
  it("computes totals + quality score", () => {
    expect(report.totalSchools).toBe(3);
    expect(report.cleanSchools).toBe(1);
    expect(report.qualityScore).toBe(33); // 1/3
    expect(report.errors).toBe(1);   // missing region
    expect(report.warnings).toBe(1); // missing enrollment
  });
  it("groups by category", () => {
    const cats = report.byCategory.map((c) => c.category);
    expect(cats).toContain("Missing region");
    expect(cats).toContain("Missing enrollment");
  });
  it("orders errors before warnings", () => {
    expect(report.issues[0].severity).toBe("Error");
  });
  it("an all-clean universe scores 100", () => {
    expect(auditSchools([clean], known).qualityScore).toBe(100);
    expect(auditSchools([], known).qualityScore).toBe(100);
  });
});
