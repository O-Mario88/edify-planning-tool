import { describe, it, expect } from "vitest";
import {
  computePortfolioComplexity,
  workloadAdjustedPace,
  classifyBand,
  buildFairMatrix,
  generateRebalanceSuggestions,
  type FairMatrixInput,
  type RebalanceInput,
} from "@/lib/performance/fwi-engine";
import type {
  PortfolioComplexityInputs,
} from "@/lib/performance/fwi-types";

// FWI is even more load-bearing than pace-status — this directly
// affects performance reviews. Tests here pin every band-boundary
// decision and the fairness math so nobody silently changes them.

// ─────────── Fixtures ───────────

function baseInputs(over: Partial<PortfolioComplexityInputs> = {}): PortfolioComplexityInputs {
  return {
    staffId: "STF-1",
    staffName: "Paul Chinyama",
    periodIso: "2026-05",
    schoolCount: 20,
    partnerSchoolCount: 5,
    districtCount: 3,
    secondaryDistrictCount: 1,
    highRiskSchoolCount: 2,
    avgSsaWeakness: 4,         // mid-range portfolio difficulty
    avgDistanceKm: 40,
    hotelTripsCount: 1,
    totalTravelKm: 600,
    partnersManaged: 1,
    specialProjectsActive: 0,
    ...over,
  };
}

// ─────────── computePortfolioComplexity ───────────

describe("computePortfolioComplexity", () => {
  it("returns a deterministic score for fixed inputs (regression guard)", () => {
    // 20×1.0 + 5×0.75 + 3×3 + 1×5 + 2×2 + 4×1.5 + (40/10)×0.5 + 1×5 + 1×4 + 0×7
    // = 20 + 3.75 + 9 + 5 + 4 + 6 + 2 + 5 + 4 + 0 = 58.75
    const r = computePortfolioComplexity(baseInputs());
    expect(r.score).toBeCloseTo(58.75, 1);
  });

  it("exposes a by-factor breakdown that sums to the score (transparency contract)", () => {
    const r = computePortfolioComplexity(baseInputs());
    const sum = Object.values(r.contributions).reduce((a, b) => a + b, 0);
    expect(Math.round(sum * 10) / 10).toBeCloseTo(r.score, 1);
  });

  it("zero portfolio scores zero (no synthetic baseline)", () => {
    const r = computePortfolioComplexity(baseInputs({
      schoolCount: 0, partnerSchoolCount: 0, districtCount: 0,
      secondaryDistrictCount: 0, highRiskSchoolCount: 0,
      avgSsaWeakness: 0, avgDistanceKm: 0,
      hotelTripsCount: 0, partnersManaged: 0, specialProjectsActive: 0,
    }));
    expect(r.score).toBe(0);
  });

  it("rewards secondary-district load — same school count, more secondary districts → higher score", () => {
    const a = computePortfolioComplexity(baseInputs({ secondaryDistrictCount: 0 }));
    const b = computePortfolioComplexity(baseInputs({ secondaryDistrictCount: 3 }));
    expect(b.score).toBeGreaterThan(a.score);
  });

  it("rewards partner-managed load", () => {
    const solo = computePortfolioComplexity(baseInputs({ partnersManaged: 0 }));
    const coordinator = computePortfolioComplexity(baseInputs({ partnersManaged: 4 }));
    expect(coordinator.score).toBeGreaterThan(solo.score);
  });

  it("custom weights override defaults faithfully", () => {
    const r = computePortfolioComplexity(baseInputs({ schoolCount: 10 }), {
      schoolWeight:           10,
      partnerSchoolWeight:    0,
      districtWeight:         0,
      secondaryDistrictWeight:0,
      highRiskWeight:         0,
      ssaWeaknessWeight:      0,
      distancePer10km:        0,
      hotelTripWeight:        0,
      partnerWeight:          0,
      specialProjectWeight:   0,
    });
    expect(r.score).toBe(100); // 10 × 10
  });
});

// ─────────── workloadAdjustedPace ───────────

describe("workloadAdjustedPace", () => {
  it("leaves median-load staff unchanged (percentile 0.5)", () => {
    expect(workloadAdjustedPace(85, 0.5)).toBe(85);
  });

  it("boosts high-load staff above raw pace", () => {
    // 95th percentile × default coeff 0.3 → centred 0.45 × 0.3 = 0.135 → +13.5%
    // 85 × 1.135 = 96.475 → 96
    expect(workloadAdjustedPace(85, 0.95)).toBe(96);
  });

  it("dampens low-load staff below raw pace", () => {
    // 5th percentile → centred -0.45 × 0.3 = -0.135 → 100 × 0.865 = 86.5 → 87
    expect(workloadAdjustedPace(100, 0.05)).toBe(87);
  });

  it("clamps to 0 floor — never produces a negative pace", () => {
    expect(workloadAdjustedPace(0, 0.05)).toBe(0);
  });

  it("zero coefficient → no fairness effect (output unchanged)", () => {
    expect(workloadAdjustedPace(80, 0.95, 0)).toBe(80);
    expect(workloadAdjustedPace(80, 0.05, 0)).toBe(80);
  });

  it("clamps percentile to [0,1] so out-of-range inputs don't blow up", () => {
    expect(workloadAdjustedPace(85, 1.5)).toBe(workloadAdjustedPace(85, 1.0));
    expect(workloadAdjustedPace(85, -0.5)).toBe(workloadAdjustedPace(85, 0.0));
  });
});

// ─────────── classifyBand ───────────

describe("classifyBand", () => {
  it("returns Establishing for probationary staff regardless of other inputs", () => {
    expect(classifyBand({
      rawPacePct: 100,
      complexityPercentile: 0.95,
      isProbationary: true,
    }).band).toBe("Establishing");
  });

  it("True Top Performer = high pace × high load", () => {
    expect(classifyBand({ rawPacePct: 88, complexityPercentile: 0.85 }).band)
      .toBe("TrueTopPerformer");
  });

  it("Consistent = high pace × low/medium load", () => {
    expect(classifyBand({ rawPacePct: 95, complexityPercentile: 0.3 }).band)
      .toBe("Consistent");
  });

  it("Overloaded = medium pace × high load (the support case, not coaching case)", () => {
    expect(classifyBand({ rawPacePct: 70, complexityPercentile: 0.9 }).band)
      .toBe("Overloaded");
  });

  it("Concern = low pace × any load", () => {
    expect(classifyBand({ rawPacePct: 55, complexityPercentile: 0.5 }).band)
      .toBe("Concern");
  });

  it("BusyLowImpact = high pace + low impact signal", () => {
    expect(classifyBand({
      rawPacePct: 95,
      complexityPercentile: 0.5,
      impactScore: 30,
    }).band).toBe("BusyLowImpact");
  });

  it("HiddenLeader takes priority over Consistent when team support is strong", () => {
    // Same pace+load that would have classified Consistent, but
    // strong team-support pushes it to HiddenLeader.
    const consistent = classifyBand({ rawPacePct: 80, complexityPercentile: 0.5 });
    expect(consistent.band).not.toBe("HiddenLeader");

    const hiddenLeader = classifyBand({
      rawPacePct: 80, complexityPercentile: 0.5, teamSupportScore: 90,
    });
    expect(hiddenLeader.band).toBe("HiddenLeader");
  });

  it("Overloaded vs BusyLowImpact discriminator is load percentile (the spec's hard rule)", () => {
    // Both staff have moderate pace. One has high load → Overloaded.
    // The other has low load → falls through to Concern.
    const overloaded = classifyBand({ rawPacePct: 70, complexityPercentile: 0.9 });
    const lowLoadCase = classifyBand({ rawPacePct: 65, complexityPercentile: 0.2 });
    expect(overloaded.band).toBe("Overloaded");
    expect(lowLoadCase.band).toBe("Concern");
  });

  it("every band returns a non-empty reason string (UI contract)", () => {
    const cases: Array<Partial<Parameters<typeof classifyBand>[0]>> = [
      { isProbationary: true },
      { rawPacePct: 88, complexityPercentile: 0.85 },
      { rawPacePct: 95, complexityPercentile: 0.3 },
      { rawPacePct: 70, complexityPercentile: 0.9 },
      { rawPacePct: 55, complexityPercentile: 0.5 },
      { rawPacePct: 95, complexityPercentile: 0.5, impactScore: 30 },
      { rawPacePct: 80, complexityPercentile: 0.5, teamSupportScore: 90 },
    ];
    for (const c of cases) {
      const r = classifyBand({ rawPacePct: 80, complexityPercentile: 0.5, ...c });
      expect(r.reason.length).toBeGreaterThan(10);
    }
  });
});

// ─────────── buildFairMatrix ───────────

describe("buildFairMatrix", () => {
  function makeStaff(staffId: string, pace: number, schoolCount: number): FairMatrixInput {
    return {
      staffId,
      staffName: `Staff ${staffId}`,
      initials: staffId.slice(-2),
      rawPacePct: pace,
      complexityInputs: baseInputs({ staffId, schoolCount }),
    };
  }

  it("returns one row per staff with all required fields populated", () => {
    const matrix = buildFairMatrix([
      makeStaff("A", 100, 10),
      makeStaff("B", 85, 30),
      makeStaff("C", 75, 50),
    ]);
    expect(matrix).toHaveLength(3);
    for (const r of matrix) {
      expect(r.staffId).toBeDefined();
      expect(r.band).toBeDefined();
      expect(r.bandReason.length).toBeGreaterThan(10);
      expect(r.complexityPercentile).toBeGreaterThanOrEqual(0);
      expect(r.complexityPercentile).toBeLessThanOrEqual(1);
    }
  });

  it("the highest-load staff lands at percentile 1, lowest at 0 (calibration)", () => {
    const matrix = buildFairMatrix([
      makeStaff("LOW", 90, 5),
      makeStaff("MID", 90, 20),
      makeStaff("HIGH", 90, 60),
    ]);
    const byId = Object.fromEntries(matrix.map((r) => [r.staffId, r]));
    expect(byId.LOW.complexityPercentile).toBe(0);
    expect(byId.HIGH.complexityPercentile).toBe(1);
  });

  it("identical staff with identical inputs receive identical bands (determinism)", () => {
    const matrix = buildFairMatrix([
      makeStaff("X1", 88, 20),
      makeStaff("X2", 88, 20),
    ]);
    expect(matrix[0].band).toBe(matrix[1].band);
    expect(matrix[0].adjustedPacePct).toBe(matrix[1].adjustedPacePct);
  });

  it("empty input returns empty output (no NaNs, no exceptions)", () => {
    expect(buildFairMatrix([])).toEqual([]);
  });

  it("high-load + decent pace gets TrueTopPerformer; low-load + perfect pace gets Consistent", () => {
    const matrix = buildFairMatrix([
      makeStaff("LIGHT", 100, 5),
      makeStaff("HEAVY", 88, 60),
    ]);
    const byId = Object.fromEntries(matrix.map((r) => [r.staffId, r]));
    expect(byId.HEAVY.band).toBe("TrueTopPerformer");
    expect(byId.LIGHT.band).toBe("Consistent");
  });
});

// ─────────── generateRebalanceSuggestions ───────────

describe("generateRebalanceSuggestions", () => {
  function makeTeam(): RebalanceInput[] {
    return [
      {
        staffId: "HEAVY",
        staffName: "Heavy Holder",
        complexityScore: 80,
        schools: [
          { schoolId: "H-S1", schoolName: "Bright Future PS",
            currentOwnerDistanceKm: 80,
            distanceFromCandidates: { LIGHT: 12, MID: 50 } },
          { schoolId: "H-S2", schoolName: "Hope Academy",
            currentOwnerDistanceKm: 90,
            distanceFromCandidates: { LIGHT: 18, MID: 60 } },
          { schoolId: "H-S3", schoolName: "Sunrise School",
            currentOwnerDistanceKm: 50,
            distanceFromCandidates: { LIGHT: 80, MID: 30 } },
        ],
      },
      {
        staffId: "MID",
        staffName: "Midway",
        complexityScore: 50,
        schools: [],
      },
      {
        staffId: "LIGHT",
        staffName: "Light Load",
        complexityScore: 20,
        schools: [],
      },
    ];
  }

  it("suggests a move from the most-overloaded to an under-loaded staff", () => {
    const recs = generateRebalanceSuggestions(makeTeam());
    expect(recs.length).toBeGreaterThan(0);
    expect(recs[0].fromStaffId).toBe("HEAVY");
    expect(recs[0].toStaffId).toBe("LIGHT"); // lightest at the moment of selection
  });

  it("picks schools that are CLOSEST to the receiver's home base, not random", () => {
    const recs = generateRebalanceSuggestions(makeTeam());
    // Schools H-S1 + H-S2 are nearest to LIGHT (12km, 18km) — should be picked
    // over H-S3 (80km from LIGHT) even though H-S3 is closer to HEAVY's own base.
    const moved = recs[0].schoolIds;
    expect(moved).toContain("H-S1");
    expect(moved).toContain("H-S2");
    expect(moved).not.toContain("H-S3");
  });

  it("returns empty when team load is balanced (no recs to make)", () => {
    const balanced: RebalanceInput[] = [
      { staffId: "A", staffName: "A", complexityScore: 50, schools: [] },
      { staffId: "B", staffName: "B", complexityScore: 48, schools: [] },
      { staffId: "C", staffName: "C", complexityScore: 52, schools: [] },
    ];
    expect(generateRebalanceSuggestions(balanced)).toEqual([]);
  });

  it("returns empty for single-staff team (nothing to compare)", () => {
    expect(generateRebalanceSuggestions([
      { staffId: "ONLY", staffName: "Only", complexityScore: 80, schools: [] },
    ])).toEqual([]);
  });

  it("produces a human-readable reason string with both names + load numbers", () => {
    const recs = generateRebalanceSuggestions(makeTeam());
    expect(recs[0].reason).toContain("Heavy Holder");
    expect(recs[0].reason).toContain("Light Load");
    expect(recs[0].reason).toMatch(/\d/); // mentions at least one number
  });

  it("ensures predicted post-move loads move toward balance (not away)", () => {
    const recs = generateRebalanceSuggestions(makeTeam());
    const r = recs[0];
    // The over-loaded staff should end LOWER; under-loaded should end HIGHER.
    expect(r.fromLoadAfter).toBeLessThan(r.fromLoadBefore);
    expect(r.toLoadAfter).toBeGreaterThan(r.toLoadBefore);
  });
});
