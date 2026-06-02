// Duplicate detection — flag (never block) school look-alikes with explained
// reasons and the Strong (85+) / Potential (60–84) banding.

import { describe, expect, it } from "vitest";
import {
  nameSimilarity,
  bandFor,
  scorePair,
  findDuplicateCandidates,
  DUPLICATE_THRESHOLDS,
} from "@/lib/intake/duplicate-detection";

describe("nameSimilarity", () => {
  it("scores identical names ~1", () => {
    expect(nameSimilarity("Nakaseke Hill Primary", "Nakaseke Hill Primary")).toBeCloseTo(1, 5);
  });
  it("scores near names high", () => {
    expect(nameSimilarity("Nakaseke Hill Primary", "Nakaseke Hills Primary School")).toBeGreaterThan(0.6);
  });
  it("scores unrelated names low", () => {
    expect(nameSimilarity("Nakaseke Hill Primary", "Gulu Hope Junior")).toBeLessThan(0.4);
  });
});

describe("bandFor", () => {
  it("bands on the spec thresholds (85 Strong, 60 Potential)", () => {
    expect(bandFor(90)).toBe("Strong");
    expect(bandFor(DUPLICATE_THRESHOLDS.strong)).toBe("Strong");
    expect(bandFor(70)).toBe("Potential");
    expect(bandFor(DUPLICATE_THRESHOLDS.potential)).toBe("Potential");
    expect(bandFor(59)).toBe("None");
  });
});

describe("scorePair", () => {
  const existing = {
    schoolId: "32791", schoolName: "Nakaseke Hill Primary",
    district: "Nakaseke", region: "Central Region", subCounty: "Nakaseke TC",
  };

  it("flags a same-district near-name as a Strong match with reasons", () => {
    const cand = {
      schoolId: "32815", schoolName: "Nakaseke Hills Primary School",
      district: "Nakaseke", region: "Central Region", subCounty: "Nakaseke TC",
    };
    const { score, reasons } = scorePair(cand, existing);
    expect(score).toBeGreaterThanOrEqual(85);
    expect(reasons.some((r) => /similar name|Identical/.test(r))).toBe(true);
    expect(reasons.some((r) => /Same district/.test(r))).toBe(true);
  });

  it("does not flag a same name in a DIFFERENT district as high (name alone isn't enough)", () => {
    const cand = { schoolId: "99999", schoolName: "Nakaseke Hill Primary", district: "Gulu", region: "Northern Region" };
    const { score } = scorePair(cand, existing);
    // Name match contributes, but absent district/region/etc it should not reach Strong.
    expect(score).toBeLessThan(DUPLICATE_THRESHOLDS.strong);
  });

  it("returns 0 for a hard same-ID collision (handled at validation, not here)", () => {
    const cand = { ...existing };
    expect(scorePair(cand, existing).score).toBe(0);
  });

  it("returns 0 when names are unrelated", () => {
    const cand = { schoolId: "70000", schoolName: "Gulu Hope Junior", district: "Nakaseke", region: "Central Region" };
    expect(scorePair(cand, existing).score).toBe(0);
  });
});

describe("findDuplicateCandidates", () => {
  it("returns flagged matches strongest-first, ignoring sub-threshold pairs", () => {
    const cand = {
      schoolId: "32815", schoolName: "Nakaseke Hills Primary School",
      district: "Nakaseke", region: "Central Region", subCounty: "Nakaseke TC",
    };
    const roster = [
      { schoolId: "32791", schoolName: "Nakaseke Hill Primary", district: "Nakaseke", region: "Central Region", subCounty: "Nakaseke TC" },
      { schoolId: "40118", schoolName: "Soroti Faith Junior", district: "Soroti", region: "Eastern Region" },
    ];
    const matches = findDuplicateCandidates(cand, roster);
    expect(matches.length).toBe(1);
    expect(matches[0].matchSchoolId).toBe("32791");
    expect(matches[0].band).toBe("Strong");
  });
});
