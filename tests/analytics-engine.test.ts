// Analytics engine — metric definitions + dedup + gates (frozen now 2025-11-15).

import { describe, expect, it } from "vitest";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";
import { isCompleted } from "@/lib/analytics/status-maps";
import { rawActivities } from "@/lib/planning/school-activity-mock";
import type { AnalyticsMetric } from "@/lib/analytics/types";

function sel(over: Partial<FilterSelection> = {}): FilterSelection {
  return {
    fy: ALL_SENTINEL, quarter: ALL_SENTINEL, region: ALL_SENTINEL, district: ALL_SENTINEL,
    cluster: ALL_SENTINEL, cceo: ALL_SENTINEL, partner: ALL_SENTINEL, package: ALL_SENTINEL,
    ssa: ALL_SENTINEL, champion: ALL_SENTINEL, ...over,
  };
}
const m = (metrics: AnalyticsMetric[], key: string) => metrics.find((x) => x.key === key)!;
const NOW = "2025-11-15";

describe("default scope (active FY 2026 cycle)", () => {
  const snap = computeAnalytics({ selection: sel(), role: "CCEO", now: NOW });
  it("scopes to the FY2026 cycle tag", () => {
    expect(snap.cycleTag).toBe("FY2026");
    expect(snap.fyId).toBe("2026");
  });
  it("schools reached = 6 distinct reached schools", () => {
    const reached = m(snap.metrics, "schoolsReached");
    expect(reached.breakdown.planned).toBe(6);
    expect(reached.records.length).toBe(6);
  });
  it("teachers trained dedup by identityKey = 9 (Aisha counted once despite 2 trainings)", () => {
    const t = m(snap.metrics, "teachersTrained");
    expect(t.value).toBe(9);
    expect(t.records.length).toBe(9);
    expect(t.records.filter((r) => r.title === "Aisha Nakato").length).toBe(1);
  });
  it("school leaders trained = 4", () => {
    expect(m(snap.metrics, "schoolLeadersTrained").value).toBe(4);
  });
  it("learners impacted = 2418, with 1 reached school missing enrollment", () => {
    const li = m(snap.metrics, "learnersImpacted");
    expect(li.value).toBe(2418);
    expect(li.records.filter((r) => !r.contributesToCount).length).toBe(1);
    expect(snap.dataQuality.notes.some((n) => /missing enrollment/i.test(n))).toBe(true);
  });
  it("districts covered = 2 (Mukono + Kayunga)", () => {
    expect(m(snap.metrics, "districtsCovered").value).toBe(2);
  });
  it("core schools reached = 3 (the NTR core-track schools)", () => {
    expect(m(snap.metrics, "coreSchoolsReached").value).toBe(3);
  });
  it("district comparison ranks Mukono (5) above Kayunga (1)", () => {
    const dc = snap.districtComparison;
    expect(dc.map((r) => r.district)).toEqual(["Mukono", "Kayunga"]);
    expect(dc[0].schoolsReached).toBe(5);
    expect(dc[0].teachersTrained).toBe(8);
    expect(dc[1].district).toBe("Kayunga");
    expect(dc[1].learnersImpacted).toBe(412);
  });
  it("activity pipeline is monotonic (planned ≥ completed ≥ verified ≥ paid)", () => {
    const [planned, completed, verified, paid] = snap.pipeline.map((s) => s.count);
    expect(planned).toBeGreaterThanOrEqual(completed);
    expect(completed).toBeGreaterThanOrEqual(verified);
    expect(verified).toBeGreaterThanOrEqual(paid);
    expect(planned).toBe(2);
    expect(paid).toBe(1);
  });
});

describe("Salesforce completion gate", () => {
  it("complete evidence WITH a valid SF id counts; WRONG prefix does not", () => {
    const valid = rawActivities.find((a) => a.id === "ACT-NTR2-1")!; // evidence complete, valid SF
    const wrong = rawActivities.find((a) => a.id === "ACT-NTR3-2")!; // evidence complete, WRONG prefix
    expect(isCompleted(valid)).toBe(true);
    expect(isCompleted(wrong)).toBe(false);
  });
});

describe("every metric carries definition + drilldown contract", () => {
  const snap = computeAnalytics({ selection: sel(), role: "CCEO", now: NOW });
  it("each metric has a definition and a breakdown", () => {
    for (const metric of snap.metrics) {
      expect(metric.definition.length).toBeGreaterThan(10);
      expect(metric.breakdown).toBeDefined();
    }
  });
});
