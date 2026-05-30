import { describe, it, expect } from "vitest";
import {
  recommendedActionsForSchool,
  recommendedActionsForPortfolio,
  type SsaSchoolSnapshot,
} from "@/lib/ssa-planning/ssa-planning";

// SSA-driven planning: SSA shouldn't only show school weakness — it
// should help staff act on it. These tests pin the rule that maps
// (area, severity) → concrete action + "Add to plan" CTA with the
// right pre-filled query params.

function snap(over: Partial<SsaSchoolSnapshot> = {}): SsaSchoolSnapshot {
  return {
    schoolId: "SCH-001",
    schoolName: "Hope Primary School",
    districtId: "DST-KITGUM",
    ssaScore: 5.5,
    weakestArea: "TeachingAndLearning",
    weakestAreaScore: 4.2,
    daysSinceLastSupportInArea: 60,
    assignedCceoId: "STF-1",
    ...over,
  };
}

describe("recommendedActionsForSchool — severity bands", () => {
  it("returns nothing for healthy schools (no actionable signal)", () => {
    expect(recommendedActionsForSchool(snap({ weakestAreaScore: 7.5 }))).toEqual([]);
  });

  it("emits priority-3 (Watch) when the weakest area is 5.5-6.9", () => {
    const r = recommendedActionsForSchool(snap({ weakestAreaScore: 6.0 }));
    expect(r).toHaveLength(1);
    expect(r[0].priority).toBe(3);
    expect(r[0].riskLevel).toBe("Medium");
  });

  it("emits priority-2 (AtRisk) when 4..5.4", () => {
    const r = recommendedActionsForSchool(snap({ weakestAreaScore: 4.5 }));
    expect(r[0].priority).toBe(2);
    expect(r[0].riskLevel).toBe("High");
  });

  it("emits priority-1 (Critical) when below 4", () => {
    const r = recommendedActionsForSchool(snap({ weakestAreaScore: 3.0 }));
    expect(r[0].priority).toBe(1);
    expect(r[0].riskLevel).toBe("Critical");
  });
});

describe("recommendedActionsForSchool — concrete CTAs", () => {
  it("primary CTA links to /plans/new pre-filled with school + activity kind", () => {
    const r = recommendedActionsForSchool(snap())[0];
    expect(r.primaryAction.label).toBe("Add to plan");
    expect(r.primaryAction.href).toContain("/plans/new");
    expect(r.primaryAction.href).toContain("schoolId=SCH-001");
    expect(r.primaryAction.href).toContain("activityKind=InSchoolCoaching");
    expect(r.primaryAction.href).toContain("suggestedBy=ssa");
  });

  it("activity kind matches the weakest area's canonical support", () => {
    expect(recommendedActionsForSchool(snap({ weakestArea: "LearningEnvironment" }))[0]
      .primaryAction.href).toContain("EnvironmentAudit");
    expect(recommendedActionsForSchool(snap({ weakestArea: "LeadershipAndGovernance" }))[0]
      .primaryAction.href).toContain("LeadershipCoaching");
    expect(recommendedActionsForSchool(snap({ weakestArea: "ParentAndCommunityEngagement" }))[0]
      .primaryAction.href).toContain("CommunityMeeting");
    expect(recommendedActionsForSchool(snap({ weakestArea: "StudentWellbeing" }))[0]
      .primaryAction.href).toContain("WellbeingVisit");
    expect(recommendedActionsForSchool(snap({ weakestArea: "AssessmentAndDataUse" }))[0]
      .primaryAction.href).toContain("AssessmentCoaching");
  });

  it("description mentions the weakest-area name and the support gap", () => {
    const r = recommendedActionsForSchool(snap({ daysSinceLastSupportInArea: 90 }))[0];
    expect(r.description).toMatch(/Teaching/i);
    expect(r.description).toContain("90 days");
  });

  it("first-time support (null daysSince) calls out that no support is on record", () => {
    const r = recommendedActionsForSchool(snap({ daysSinceLastSupportInArea: null }))[0];
    expect(r.description).toMatch(/No support recorded/i);
  });
});

describe("recommendedActionsForPortfolio — bulk", () => {
  it("returns recommendations for all weak schools, sorted Critical-first", () => {
    const recs = recommendedActionsForPortfolio([
      snap({ schoolId: "S1", weakestAreaScore: 6.0 }),
      snap({ schoolId: "S2", weakestAreaScore: 3.0 }),
      snap({ schoolId: "S3", weakestAreaScore: 8.0 }), // healthy → no rec
      snap({ schoolId: "S4", weakestAreaScore: 4.5 }),
    ]);
    expect(recs).toHaveLength(3); // S3 excluded
    expect(recs[0].priority).toBe(1); // S2 (Critical) first
    expect(recs[2].priority).toBe(3); // S1 (Watch) last
  });

  it("returns empty for a fully healthy portfolio", () => {
    expect(recommendedActionsForPortfolio([
      snap({ schoolId: "S1", weakestAreaScore: 8.0 }),
      snap({ schoolId: "S2", weakestAreaScore: 9.0 }),
    ])).toEqual([]);
  });
});
