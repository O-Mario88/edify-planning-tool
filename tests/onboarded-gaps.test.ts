// Onboarded schools → planner gaps + supervision scoping.

import { describe, expect, it } from "vitest";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";
import type { SchoolGap } from "@/lib/planning/planning-gaps-mock";

describe("onboardedSchoolGaps", () => {
  const gaps = onboardedSchoolGaps();
  it("produces one gap per onboarded school", () => {
    expect(gaps.length).toBeGreaterThanOrEqual(2); // the two seeds
    for (const g of gaps) expect(g.id.startsWith("onb-")).toBe(true);
  });
  it("an UNCLUSTERED school is a no_cluster gap, even with no SSA", () => {
    // Seed 32791 (Nakaseke) is SSA Not Done AND not in a cluster. The operating
    // model gates in order: owner → cluster → SSA. So the FIRST unmet gate wins:
    // an unclustered school is no_cluster (clustering unlocks SSA), not no_ssa.
    const nakaseke = gaps.find((g) => g.id === "onb-32791");
    expect(nakaseke?.gapCategory).toBe("no_cluster");
    expect(nakaseke?.ssaCompleted).toBe(false);
    expect(nakaseke?.riskLevel).toBe("High");
  });
  it("maps uploaded SSA scores onto planner intervention areas when present", () => {
    // Any gap that has a weakestArea must use a planning-area label.
    const PLANNING_AREAS = new Set([
      "Teaching & Learning", "Financial Health", "Christlike Behaviour",
      "Exposure to the Word of God", "Government Requirements & Compliance",
      "Leadership", "Education Technology", "Learning Environment",
    ]);
    for (const g of gaps) {
      if (g.weakestArea) expect(PLANNING_AREAS.has(g.weakestArea.area)).toBe(true);
    }
  });
});

describe("scopeGapsToViewer", () => {
  const sample: SchoolGap[] = [
    { id: "a", schoolName: "A", district: "Wakiso", subCounty: "", assignedCceo: "Paul Chinyama", ssaCompleted: false, inCluster: false, riskLevel: "Critical", gapCategory: "no_ssa" },
    { id: "b", schoolName: "B", district: "Gulu", subCounty: "", assignedCceo: "Abdi Hassan", ssaCompleted: false, inCluster: false, riskLevel: "Critical", gapCategory: "no_ssa" },
    { id: "c", schoolName: "C", district: "X", subCounty: "", assignedCceo: "Unknown Person", ssaCompleted: false, inCluster: false, riskLevel: "Critical", gapCategory: "no_ssa" },
  ];
  it("a Program Lead sees only their supervised CCEOs' schools (+ unresolvable owners)", () => {
    // Daniel (STF-DM-014) supervises Paul, not Abdi (Aisha's).
    const r = scopeGapsToViewer(sample, "STF-DM-014", "CountryProgramLead").map((g) => g.id);
    expect(r).toContain("a"); // Paul → Daniel
    expect(r).not.toContain("b"); // Abdi → Aisha
    expect(r).toContain("c"); // unknown owner kept
  });
  it("Country Director / RVP / Admin see everything", () => {
    expect(scopeGapsToViewer(sample, "STF-SO-007", "CountryDirector")).toHaveLength(3);
    expect(scopeGapsToViewer(sample, "STF-EW-003", "RVP")).toHaveLength(3);
  });
});
