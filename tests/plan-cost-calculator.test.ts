import { describe, it, expect } from "vitest";
import {
  calculateStaffVisitCost,
  calculateParticipantBasedCost,
  calculatePartnerVisitCost,
  maxTrainingsPerDay,
  validateTrainingDayCapacity,
  recommendPurpose,
  allowedStaffPurposes,
  allowedPartnerPurposes,
  partnerVisitBlocker,
  type PlanCostRates,
} from "@/lib/plan-cost-calculator";
import type { SchoolVisitRecommendation } from "@/lib/plan-builder-engine";

// Test rate table — values chosen so calculations have clean integer
// totals for assertion readability.
const RATES: PlanCostRates = {
  staffCommutingTransport:        10_000,
  staffLunch:                      5_000,
  staffOvernightTransport:        20_000,
  breakfastPerDay:                 3_000,
  lunchPerDay:                     5_000,
  dinnerPerDay:                    4_000,
  accommodationPerNight:          30_000,
  clusterTrainingPerParticipant:   8_000,
  clusterMeetingPerParticipant:    4_000,
  venueFee:                       50_000,
  facilitationFee:                25_000,
  partnerVisitCostPerSchool:      12_000,
  partnerTrainingFacilitationFee: 40_000,
  partnerFacilitatorDailyFee:     35_000,
};

describe("calculateStaffVisitCost — commuting", () => {
  it("computes per-staff cost as transport + lunch and multiplies by staff × schools", () => {
    const out = calculateStaffVisitCost(
      { visitType: "Commuting Visit", staffCount: 2, schoolCount: 3 },
      RATES,
    );
    // (10,000 + 5,000) × 2 staff × 3 schools = 90,000
    expect(out.perStaff).toBe(15_000);
    expect(out.total).toBe(90_000);
    expect(out.accommodation).toBe(0);
    expect(out.breakfast).toBe(0);
    expect(out.dinner).toBe(0);
  });

  it("treats sub-1 staff as 1 (no negative or zero cost)", () => {
    const out = calculateStaffVisitCost(
      { visitType: "Commuting Visit", staffCount: 0, schoolCount: 1 },
      RATES,
    );
    expect(out.total).toBe(15_000);
  });

  it("returns an empty breakdown when 0 schools are selected (do not invent cost)", () => {
    const out = calculateStaffVisitCost(
      { visitType: "Commuting Visit", staffCount: 5, schoolCount: 0 },
      RATES,
    );
    expect(out.total).toBe(0);
    expect(out.formula).toMatch(/0 schools/);
  });
});

describe("calculateStaffVisitCost — overnight", () => {
  it("includes breakfast/lunch/dinner per day and accommodation per night", () => {
    const out = calculateStaffVisitCost(
      { visitType: "Overnight Visit", staffCount: 1, schoolCount: 1, nights: 2, days: 3 },
      RATES,
    );
    // transport 20,000 + breakfast 3,000×3 + lunch 5,000×3 + dinner 4,000×3 + accom 30,000×2
    // = 20,000 + 9,000 + 15,000 + 12,000 + 60,000 = 116,000
    expect(out.transport).toBe(20_000);
    expect(out.breakfast).toBe(9_000);
    expect(out.lunch).toBe(15_000);
    expect(out.dinner).toBe(12_000);
    expect(out.accommodation).toBe(60_000);
    expect(out.perStaff).toBe(116_000);
    expect(out.total).toBe(116_000);
  });

  it("clamps nights to never exceed days", () => {
    // 1 day but 5 nights claimed: nights should clamp to 1.
    const out = calculateStaffVisitCost(
      { visitType: "Overnight Visit", staffCount: 1, schoolCount: 1, nights: 5, days: 1 },
      RATES,
    );
    expect(out.accommodation).toBe(30_000); // 1 night, not 5
  });

  it("defaults days to nights+1 when days isn't passed", () => {
    const out = calculateStaffVisitCost(
      { visitType: "Overnight Visit", staffCount: 1, schoolCount: 1, nights: 2 },
      RATES,
    );
    // days defaults to nights+1 = 3.
    expect(out.breakfast).toBe(3_000 * 3);
  });
});

describe("calculateParticipantBasedCost", () => {
  it("computes feeding × participants for a Cluster Training", () => {
    const out = calculateParticipantBasedCost(
      { activity: "Cluster Training", participants: 10, includeVenue: false, includeFacilitation: false },
      RATES,
    );
    expect(out.feeding).toBe(80_000); // 10 × 8,000
    expect(out.venue).toBe(0);
    expect(out.facilitation).toBe(0);
    expect(out.total).toBe(80_000);
  });

  it("adds venue + facilitation when toggled on", () => {
    const out = calculateParticipantBasedCost(
      { activity: "Cluster Training", participants: 10, includeVenue: true, includeFacilitation: true },
      RATES,
    );
    expect(out.total).toBe(80_000 + 50_000 + 25_000);
  });

  it("uses the cheaper meeting rate for Cluster Meetings", () => {
    const out = calculateParticipantBasedCost(
      { activity: "Cluster Meeting", participants: 10, includeVenue: false, includeFacilitation: false },
      RATES,
    );
    expect(out.feeding).toBe(40_000); // 10 × 4,000
  });

  it("treats negative participants as zero", () => {
    const out = calculateParticipantBasedCost(
      { activity: "Cluster Training", participants: -5, includeVenue: false, includeFacilitation: false },
      RATES,
    );
    expect(out.feeding).toBe(0);
  });
});

describe("calculatePartnerVisitCost", () => {
  it("computes per-school × school count", () => {
    const out = calculatePartnerVisitCost({ schoolCount: 4 }, RATES);
    expect(out.total).toBe(48_000); // 4 × 12,000
  });

  it("returns zero on zero schools", () => {
    const out = calculatePartnerVisitCost({ schoolCount: 0 }, RATES);
    expect(out.total).toBe(0);
  });
});

describe("maxTrainingsPerDay", () => {
  it("returns the facilitator count as the daily cap", () => {
    expect(maxTrainingsPerDay(3)).toBe(3);
  });

  it("floors at 1 to preserve a non-zero cap", () => {
    expect(maxTrainingsPerDay(0)).toBe(1);
  });

  it("floors fractional facilitators", () => {
    expect(maxTrainingsPerDay(2.7)).toBe(2);
  });
});

describe("validateTrainingDayCapacity", () => {
  it("returns no warnings when planned ≤ cap on every day", () => {
    const warnings = validateTrainingDayCapacity(2, {
      "2026-06-02": 2,
      "2026-06-03": 1,
    });
    expect(warnings).toEqual([]);
  });

  it("returns an error warning for any day over the cap", () => {
    const warnings = validateTrainingDayCapacity(2, {
      "2026-06-02": 3,
      "2026-06-03": 1,
    });
    expect(warnings).toHaveLength(1);
    expect(warnings[0].level).toBe("error");
    expect(warnings[0].message).toContain("3 cluster trainings");
    expect(warnings[0].message).toContain("2 facilitators");
  });
});

// ────────── Visit-purpose recommendation rules ──────────

function fixture(over: Partial<SchoolVisitRecommendation> = {}): SchoolVisitRecommendation {
  // Build a complete-enough fixture so tests don't have to know every
  // unrelated field on the recommendation type.
  return {
    schoolId: "SCH-001",
    schoolName: "Test School",
    district: "Kampala",
    cluster: "C-1",
    ssaScore: 7.0,
    weakestIntervention: "Literacy",
    lastVisitDate: "2026-04-12",
    lastTrainingDate: "—",
    priorityReason: "",
    assignedCceo: "CCEO-1",
    coreSchool: true,
    coverageStatus: "OnTrack",
    region: "Central",
    schoolType: "Primary",
    learners: 480,
    teachers: 18,
    interventionSummary: {} as never,
    ...over,
  } as SchoolVisitRecommendation;
}

describe("recommendPurpose", () => {
  it("offers SSA Support and only SSA Support when no SSA on record", () => {
    const r = recommendPurpose(fixture({ ssaScore: null }));
    expect(r.primary).toBe("SSA Support");
    expect(r.secondary).toBeUndefined();
    expect(allowedStaffPurposes(fixture({ ssaScore: null }))).toEqual(["SSA Support"]);
  });

  it("flags priorityBoost when SSA weak + recently trained + visit gap", () => {
    const r = recommendPurpose(
      fixture({ ssaScore: 4.5, lastTrainingDate: "2026-04-01", lastVisitDate: "—" }),
    );
    expect(r.priorityBoost).toBe(true);
    expect(r.primary).toBe("Training Follow-Up");
    expect(r.secondary).toBe("In-School Coaching");
  });

  it("recommends Core School Visit when nothing is off", () => {
    const r = recommendPurpose(fixture({ ssaScore: 7.5, lastVisitDate: "2026-04-12" }));
    expect(r.primary).toBe("Core School Visit");
    expect(r.priorityBoost).toBe(false);
  });
});

describe("partnerVisitBlocker", () => {
  it("blocks SSA Verification for partners (staff-only)", () => {
    expect(
      partnerVisitBlocker(fixture(), "SSA Verification", true, true),
    ).toMatch(/staff/i);
  });

  it("blocks Data Collection unless the school is scheduled for an SSA visit", () => {
    expect(
      partnerVisitBlocker(fixture(), "Data Collection", true, false),
    ).toMatch(/SSA/);
  });

  it("blocks non-certified partners from doing coaching", () => {
    expect(
      partnerVisitBlocker(fixture(), "In-School Coaching", false, false),
    ).toMatch(/non-certified/i);
  });

  it("blocks non-certified Courtesy Visit on a school that already has a current-FY SSA", () => {
    expect(
      partnerVisitBlocker(fixture({ ssaScore: 7.0 }), "Courtesy Visit", false, false),
    ).toMatch(/can't perform Courtesy Visits/);
  });

  it("returns null when the assignment is valid", () => {
    expect(
      partnerVisitBlocker(fixture({ ssaScore: null }), "Courtesy Visit", false, false),
    ).toBeNull();
  });
});

describe("allowedPartnerPurposes", () => {
  it("limits non-certified partners to Courtesy Visit when no SSA visit is scheduled", () => {
    expect(allowedPartnerPurposes(false, false)).toEqual(["Courtesy Visit"]);
  });

  it("adds Data Collection for non-certified partners on schools scheduled for SSA", () => {
    expect(allowedPartnerPurposes(false, true)).toEqual([
      "Data Collection",
      "Courtesy Visit",
    ]);
  });

  it("never offers SSA Verification to partners", () => {
    expect(allowedPartnerPurposes(true, true)).not.toContain("SSA Verification");
  });
});
