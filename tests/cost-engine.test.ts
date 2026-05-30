// Cost engine tests.
//
// Locking in the CD's rules (May 2026):
//   • Staff primary district:   56k transport/school + 30k lunch/day
//   • Staff secondary district: 66k transport/school + 30k lunch + 20k breakfast
//                              + 50k dinner + 150k accommodation/night
//                              (breakfast, dinner, accommodation auto-included)
//   • Partner:                  40k lump sum per school
//   • Any secondary school in trip → secondary rates apply ("no half-overnight")

import { describe, expect, it } from "vitest";
import {
  computeVisitCost,
  deriveDistrictType,
  type SchoolStop,
  type VisitCostRates,
} from "@/lib/cost-engine/cost-engine";

const RATES: VisitCostRates = {
  staffPrimaryTransportPerSchool:   56_000,
  staffSecondaryTransportPerSchool: 66_000,
  staffLunchPerDay:                 30_000,
  staffBreakfastPerDay:             20_000,
  staffDinnerPerDay:                50_000,
  staffAccommodationPerNight:      150_000,
  partnerLumpSumPerSchool:          40_000,
};

const primarySchool = (id = "S-PRI-1", name = "Hope Primary"): SchoolStop => ({
  schoolId: id,
  schoolName: name,
  districtType: "primary",
});

const secondarySchool = (id = "S-SEC-1", name = "Far Reach Primary"): SchoolStop => ({
  schoolId: id,
  schoolName: name,
  districtType: "secondary",
});

describe("computeVisitCost — partner", () => {
  it("partner visit: 1 school = 40,000 UGX lump sum", () => {
    const result = computeVisitCost({ mode: "partner", schools: [primarySchool()], rates: RATES });
    expect(result.totalUgx).toBe(40_000);
    expect(result.lines).toHaveLength(1);
    expect(result.lines[0].kind).toBe("partner-lump-sum");
    expect(result.overnightRequired).toBe(false);
  });

  it("partner visit: 3 schools = 120,000 UGX", () => {
    const result = computeVisitCost({
      mode: "partner",
      schools: [primarySchool("a"), primarySchool("b"), secondarySchool("c")],
      rates: RATES,
    });
    // Partner lump sum ignores primary/secondary — flat 40k per school.
    expect(result.totalUgx).toBe(120_000);
    expect(result.lines).toHaveLength(1);
    expect(result.lines[0].qty).toBe(3);
  });
});

describe("computeVisitCost — staff primary district", () => {
  it("staff visit, 1 school, 1 day: 56k transport + 30k lunch = 86k", () => {
    const result = computeVisitCost({ mode: "staff", schools: [primarySchool()], rates: RATES });
    expect(result.totalUgx).toBe(86_000);
    expect(result.tripDistrictType).toBe("primary");
    expect(result.overnightRequired).toBe(false);
    const transport = result.lines.find((l) => l.kind === "transport")!;
    expect(transport.unitCost).toBe(56_000);
    expect(transport.qty).toBe(1);
  });

  it("staff visit, 5 schools primary district, 1 day: 5×56k + 30k = 310k (CD example)", () => {
    // The CD's exact example: 5 schools in primary district. Transport
    // alone is 5 × 56k = 280k; plus 30k lunch = 310k total.
    const result = computeVisitCost({
      mode: "staff",
      schools: [1, 2, 3, 4, 5].map((i) => primarySchool(`s-${i}`)),
      rates: RATES,
    });
    const transport = result.lines.find((l) => l.kind === "transport")!;
    expect(transport.amountUgx).toBe(280_000); // ← the CD's anchor number
    expect(result.totalUgx).toBe(310_000);
  });

  it("staff visit, 2 schools, 2 days primary: 2×56k + 2×30k = 172k", () => {
    const result = computeVisitCost({
      mode: "staff",
      schools: [primarySchool("a"), primarySchool("b")],
      days: 2,
      rates: RATES,
    });
    expect(result.totalUgx).toBe(2 * 56_000 + 2 * 30_000);
    expect(result.lines.find((l) => l.kind === "dinner")).toBeUndefined();
    expect(result.lines.find((l) => l.kind === "accommodation")).toBeUndefined();
  });
});

describe("computeVisitCost — staff secondary district", () => {
  it("staff visit, 1 school secondary, 1 day: 66k transport + 20k breakfast + 30k lunch + 50k dinner = 166k (no overnight night since days=1)", () => {
    const result = computeVisitCost({ mode: "staff", schools: [secondarySchool()], rates: RATES });
    expect(result.tripDistrictType).toBe("secondary");
    expect(result.overnightRequired).toBe(true);
    expect(result.nights).toBe(0);
    expect(result.totalUgx).toBe(66_000 + 20_000 + 30_000 + 50_000); // = 166,000
    expect(result.lines.find((l) => l.kind === "accommodation")).toBeUndefined();
  });

  it("staff visit, 1 school secondary, 2 days, 1 night: 66k + 40k breakfast + 60k lunch + 100k dinner + 150k accom = 416k", () => {
    const result = computeVisitCost({
      mode: "staff",
      schools: [secondarySchool()],
      days: 2,
      rates: RATES,
    });
    expect(result.nights).toBe(1);
    expect(result.totalUgx).toBe(66_000 + 2 * 20_000 + 2 * 30_000 + 2 * 50_000 + 150_000);
    const accom = result.lines.find((l) => l.kind === "accommodation")!;
    expect(accom.qty).toBe(1);
    expect(accom.unitCost).toBe(150_000);
    expect(accom.note).toContain("Auto-included");
  });

  it("staff visit, 3 schools secondary, 2 days: 3×66k + 2×20k + 2×30k + 2×50k + 1×150k", () => {
    const result = computeVisitCost({
      mode: "staff",
      schools: [secondarySchool("a"), secondarySchool("b"), secondarySchool("c")],
      days: 2,
      rates: RATES,
    });
    expect(result.totalUgx).toBe(3 * 66_000 + 2 * 20_000 + 2 * 30_000 + 2 * 50_000 + 150_000);
  });

  it("overnight nights default to max(0, days - 1)", () => {
    const oneDay   = computeVisitCost({ mode: "staff", schools: [secondarySchool()], days: 1, rates: RATES });
    const twoDay   = computeVisitCost({ mode: "staff", schools: [secondarySchool()], days: 2, rates: RATES });
    const threeDay = computeVisitCost({ mode: "staff", schools: [secondarySchool()], days: 3, rates: RATES });
    expect(oneDay.nights).toBe(0);
    expect(twoDay.nights).toBe(1);
    expect(threeDay.nights).toBe(2);
  });
});

describe("computeVisitCost — mixed-district trip", () => {
  it("any secondary school on the trip → entire trip prices at secondary rates", () => {
    const result = computeVisitCost({
      mode: "staff",
      schools: [primarySchool("a"), primarySchool("b"), secondarySchool("c")],
      days: 2,
      rates: RATES,
    });
    expect(result.tripDistrictType).toBe("secondary");
    expect(result.overnightRequired).toBe(true);
    // Transport rate is the secondary rate (66k) applied to ALL 3 schools.
    const transport = result.lines.find((l) => l.kind === "transport")!;
    expect(transport.unitCost).toBe(66_000);
    expect(transport.qty).toBe(3);
    expect(result.lines.find((l) => l.kind === "dinner")).toBeDefined();
    expect(result.lines.find((l) => l.kind === "accommodation")).toBeDefined();
  });
});

describe("missingRates", () => {
  it("flags zero rates for primary visit", () => {
    const rates: VisitCostRates = { ...RATES, staffPrimaryTransportPerSchool: 0, staffLunchPerDay: 0 };
    const result = computeVisitCost({ mode: "staff", schools: [primarySchool()], rates });
    expect(result.missingRates).toEqual(
      expect.arrayContaining(["staffPrimaryTransportPerSchool", "staffLunchPerDay"]),
    );
  });

  it("flags partner lump sum when zero", () => {
    const rates: VisitCostRates = { ...RATES, partnerLumpSumPerSchool: 0 };
    const result = computeVisitCost({ mode: "partner", schools: [primarySchool()], rates });
    expect(result.missingRates).toEqual(["partnerLumpSumPerSchool"]);
  });
});

describe("deriveDistrictType", () => {
  it("matching districts → primary", () => {
    expect(deriveDistrictType("D-MUKONO", "D-MUKONO")).toBe("primary");
  });
  it("different districts → secondary", () => {
    expect(deriveDistrictType("D-MUKONO", "D-KITGUM")).toBe("secondary");
  });
});

describe("breakdown line ordering", () => {
  it("lines emit in display order: transport, lunch, breakfast, dinner, accommodation", () => {
    const result = computeVisitCost({ mode: "staff", schools: [secondarySchool()], days: 2, rates: RATES });
    const kinds = result.lines.map((l) => l.kind);
    expect(kinds).toEqual(["transport", "lunch", "breakfast", "dinner", "accommodation"]);
  });
});
