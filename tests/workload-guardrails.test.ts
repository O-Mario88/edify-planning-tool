import { describe, it, expect } from "vitest";
import {
  detectWorkloadFlags,
  recommendInterventions,
  DEFAULT_WORKLOAD_THRESHOLDS,
  type WorkloadDetectionInput,
} from "@/lib/workload/workload-guardrails";

// Workload guardrails sit between staff and "unfair judgment" — the
// product principle says these flags must fire when (and only when)
// the load is genuinely above the healthy cap. Tests below pin each
// rule individually so a change to one threshold can't silently shift
// who shows up on the HR watchlist.

function input(over: Partial<WorkloadDetectionInput> = {}): WorkloadDetectionInput {
  return {
    staffId: "STF-1",
    staffName: "Paul Chinyama",
    portfolio: {
      staffId: "STF-1",
      staffName: "Paul Chinyama",
      periodIso: "2026-05",
      schoolCount: 20,
      partnerSchoolCount: 4,
      districtCount: 2,
      secondaryDistrictCount: 0,
      highRiskSchoolCount: 1,
      avgSsaWeakness: 4,
      avgDistanceKm: 30,
      hotelTripsCount: 0,
      totalTravelKm: 400,
      partnersManaged: 1,
      specialProjectsActive: 0,
    },
    pendingTaskCount: 5,
    specialProjectsActive: 0,
    avgDailyTravelKm: 30,
    ...over,
  };
}

// ─────────── Detection — green path ───────────

describe("detectWorkloadFlags — green portfolio", () => {
  it("returns no flags for a balanced load", () => {
    expect(detectWorkloadFlags(input())).toEqual([]);
  });
});

// ─────────── Detection — every individual flag ───────────

describe("detectWorkloadFlags — individual rules", () => {
  it("flags TooManySchools when above cap", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 48 },
    }));
    expect(flags.map((f) => f.kind)).toContain("TooManySchools");
  });

  it("flags TooManyDistricts", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, districtCount: 7 },
    }));
    expect(flags.map((f) => f.kind)).toContain("TooManyDistricts");
  });

  it("flags TooManySecondaryDistricts", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, secondaryDistrictCount: 5 },
    }));
    expect(flags.map((f) => f.kind)).toContain("TooManySecondaryDistricts");
  });

  it("flags HighDailyTravelKm based on the 4-week average", () => {
    const flags = detectWorkloadFlags(input({ avgDailyTravelKm: 110 }));
    expect(flags.map((f) => f.kind)).toContain("HighDailyTravelKm");
  });

  it("flags TooManyPartnersManaged", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, partnersManaged: 6 },
    }));
    expect(flags.map((f) => f.kind)).toContain("TooManyPartnersManaged");
  });

  it("flags TooManyPendingTasks (inbox overload, distinct from portfolio)", () => {
    const flags = detectWorkloadFlags(input({ pendingTaskCount: 40 }));
    expect(flags.map((f) => f.kind)).toContain("TooManyPendingTasks");
  });

  it("flags TooManySpecialProjects", () => {
    const flags = detectWorkloadFlags(input({ specialProjectsActive: 4 }));
    expect(flags.map((f) => f.kind)).toContain("TooManySpecialProjects");
  });

  it("flags RepeatedHotelTrips", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, hotelTripsCount: 9 },
    }));
    expect(flags.map((f) => f.kind)).toContain("RepeatedHotelTrips");
  });

  it("flags HighTargetUnderHighLoad only when BOTH conditions hold", () => {
    // High load alone — no flag for this kind.
    const justLoad = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 39 }, // near cap (cap=40 → 85% of cap = 34)
    }));
    expect(justLoad.map((f) => f.kind)).not.toContain("HighTargetUnderHighLoad");

    // High load + high target — flag fires.
    const bothConditions = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 39 },
      targetRatioVsMedian: 1.20,
    }));
    expect(bothConditions.map((f) => f.kind)).toContain("HighTargetUnderHighLoad");
  });

  it("severity scales with how far over the cap the staff is", () => {
    const slightlyOver = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 42 }, // 5% over
    }));
    const wayOver = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 70 }, // 75% over
    }));
    const slight = slightlyOver.find((f) => f.kind === "TooManySchools")!;
    const big    = wayOver.find((f) => f.kind === "TooManySchools")!;
    expect(big.severity).toBeGreaterThan(slight.severity);
  });
});

// ─────────── Detection — message tone ───────────

describe("detectWorkloadFlags — supportive language", () => {
  it("every flag's message is observation-style, not accusatory", () => {
    const flags = detectWorkloadFlags(input({
      portfolio: { ...input().portfolio, schoolCount: 60, partnersManaged: 6, hotelTripsCount: 9 },
      pendingTaskCount: 35,
      avgDailyTravelKm: 120,
      specialProjectsActive: 4,
    }));
    // Heuristic: no "failed", "missed", "behind", "warning" — words
    // the HR / CPL spec asks us to avoid in fairness language.
    for (const f of flags) {
      expect(f.message).not.toMatch(/failed|missed|behind|warning/i);
    }
    expect(flags.length).toBeGreaterThanOrEqual(5);
  });
});

// ─────────── Recommendation engine ───────────

describe("recommendInterventions — single-flag scenarios", () => {
  it("TooManySchools → RebalanceSchools with concrete count", () => {
    const inp = input({ portfolio: { ...input().portfolio, schoolCount: 48 } });
    const flags = detectWorkloadFlags(inp);
    const recs = recommendInterventions(inp, flags);
    const rebal = recs.find((r) => r.kind === "RebalanceSchools");
    expect(rebal).toBeDefined();
    expect(rebal!.message).toMatch(/8/);   // 48 - 40 = 8 schools to move
  });

  it("HighTargetUnderHighLoad → ReduceTarget", () => {
    const inp = input({
      portfolio: { ...input().portfolio, schoolCount: 39 },
      targetRatioVsMedian: 1.20,
    });
    const flags = detectWorkloadFlags(inp);
    const recs = recommendInterventions(inp, flags);
    expect(recs.map((r) => r.kind)).toContain("ReduceTarget");
  });

  it("TooManyPartnersManaged → AddPartnerSupport", () => {
    const inp = input({ portfolio: { ...input().portfolio, partnersManaged: 6 } });
    const flags = detectWorkloadFlags(inp);
    expect(recommendInterventions(inp, flags).map((r) => r.kind)).toContain("AddPartnerSupport");
  });

  it("HighDailyTravelKm OR RepeatedHotelTrips → ApproveTravelSupport", () => {
    const inp1 = input({ avgDailyTravelKm: 110 });
    expect(recommendInterventions(inp1, detectWorkloadFlags(inp1)).map((r) => r.kind))
      .toContain("ApproveTravelSupport");

    const inp2 = input({ portfolio: { ...input().portfolio, hotelTripsCount: 9 } });
    expect(recommendInterventions(inp2, detectWorkloadFlags(inp2)).map((r) => r.kind))
      .toContain("ApproveTravelSupport");
  });

  it("TooManyPendingTasks → AssignCoaching", () => {
    const inp = input({ pendingTaskCount: 40 });
    expect(recommendInterventions(inp, detectWorkloadFlags(inp)).map((r) => r.kind))
      .toContain("AssignCoaching");
  });

  it("TooManySpecialProjects → RedistributeProjects with concrete count", () => {
    const inp = input({ specialProjectsActive: 5 });
    const rec = recommendInterventions(inp, detectWorkloadFlags(inp)).find((r) => r.kind === "RedistributeProjects");
    expect(rec).toBeDefined();
    expect(rec!.message).toMatch(/3/);   // 5 - 2 = 3 to reassign
  });

  it("returns empty when no flags fire", () => {
    expect(recommendInterventions(input(), [])).toEqual([]);
  });

  it("recommendations are ordered by priority — strongest intervention first", () => {
    const inp = input({
      portfolio: { ...input().portfolio, schoolCount: 60, partnersManaged: 6, hotelTripsCount: 9 },
      pendingTaskCount: 35,
      avgDailyTravelKm: 120,
      specialProjectsActive: 5,
      targetRatioVsMedian: 1.20,
    });
    const recs = recommendInterventions(inp, detectWorkloadFlags(inp));
    // RebalanceSchools (90) should come before AssignCoaching (50).
    const rebal = recs.findIndex((r) => r.kind === "RebalanceSchools");
    const coach = recs.findIndex((r) => r.kind === "AssignCoaching");
    expect(rebal).toBeLessThan(coach);
  });
});

// ─────────── Thresholds are tunable ───────────

describe("custom thresholds override defaults", () => {
  it("a country with a higher cap won't flag the same staff", () => {
    const inp = input({ portfolio: { ...input().portfolio, schoolCount: 42 } });
    const strict = detectWorkloadFlags(inp);
    const relaxed = detectWorkloadFlags(inp, { ...DEFAULT_WORKLOAD_THRESHOLDS, maxSchools: 60 });
    expect(strict.some((f) => f.kind === "TooManySchools")).toBe(true);
    expect(relaxed.some((f) => f.kind === "TooManySchools")).toBe(false);
  });
});
