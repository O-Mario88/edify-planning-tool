// Cumulative period-target engine — the spec's worked examples.

import { describe, expect, it } from "vitest";
import { computePeriodTarget } from "@/lib/targets/period-target";
import {
  CCEO_ANNUAL_TARGET,
  PL_ANNUAL_TARGET,
  fyTargetForRole,
} from "@/lib/targets/role-targets";

const base = { selectedFy: "2026", achieved: 0, now: "2025-11-15" };

describe("cumulative expected targets — CCEO 560", () => {
  it("Q1 140 · Mid-Year 280 · Q3 420 · Q4 560", () => {
    expect(computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q1" }).expectedCumulative).toBe(140);
    expect(computePeriodTarget({ ...base, fyTarget: 560, periodType: "MidYear" }).expectedCumulative).toBe(280);
    expect(computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q2" }).expectedCumulative).toBe(280);
    expect(computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q3" }).expectedCumulative).toBe(420);
    expect(computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q4" }).expectedCumulative).toBe(560);
  });
});

describe("cumulative expected targets — PL 280 (separate from CCEO)", () => {
  it("70 · 140 · 210 · 280", () => {
    expect(computePeriodTarget({ ...base, fyTarget: 280, selectedQuarter: "Q1" }).expectedCumulative).toBe(70);
    expect(computePeriodTarget({ ...base, fyTarget: 280, selectedQuarter: "Q2" }).expectedCumulative).toBe(140);
    expect(computePeriodTarget({ ...base, fyTarget: 280, selectedQuarter: "Q3" }).expectedCumulative).toBe(210);
    expect(computePeriodTarget({ ...base, fyTarget: 280, selectedQuarter: "Q4" }).expectedCumulative).toBe(280);
  });
});

describe("role targets", () => {
  it("CCEO 560, PL 280, never crossed", () => {
    expect(CCEO_ANNUAL_TARGET).toBe(560);
    expect(PL_ANNUAL_TARGET).toBe(280);
    expect(fyTargetForRole("CCEO")).toBe(560);
    expect(fyTargetForRole("CountryProgramLead")).toBe(280);
  });
});

describe("mid-year = end of Q2 = 50%", () => {
  it("MidYear and Q2 agree at 50%", () => {
    const mid = computePeriodTarget({ ...base, fyTarget: 560, periodType: "MidYear" });
    const q2 = computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q2" });
    expect(mid.expectedPct).toBe(0.5);
    expect(q2.expectedPct).toBe(0.5);
    expect(mid.expectedCumulative).toBe(q2.expectedCumulative);
  });
});

describe("gap, pace, remaining, projection", () => {
  it("behind at mid-year", () => {
    const r = computePeriodTarget({ ...base, fyTarget: 560, periodType: "MidYear", achieved: 200 });
    expect(r.expectedCumulative).toBe(280);
    expect(r.gapToExpected).toBe(-80);
    expect(r.remaining).toBe(360);
    expect(r.paceStatus).toBe("Behind"); // 200/280 ≈ 0.71
  });

  it("ahead in Q1", () => {
    const r = computePeriodTarget({ ...base, fyTarget: 560, selectedQuarter: "Q1", achieved: 160 });
    expect(r.paceStatus).toBe("Ahead"); // 160/140 ≈ 1.14
    expect(r.projectedFyCompletion).toBe(640); // 160 / 0.25
  });

  it("FY view uses time-elapsed expected (not 100%)", () => {
    const r = computePeriodTarget({ ...base, fyTarget: 560, achieved: 50 });
    expect(r.periodType).toBe("FY");
    expect(r.expectedPct).toBeGreaterThan(0.1); // ~45/364 ≈ 0.124 in mid-November
    expect(r.expectedPct).toBeLessThan(0.16);
  });
});
