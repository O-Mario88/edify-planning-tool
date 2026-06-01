// Analytics scoping — geography + FY/quarter narrow the data (not just the UI).

import { describe, expect, it } from "vitest";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";
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

describe("district filter narrows the data (not just the chrome)", () => {
  it("district = Mukono → only Mukono's 5 reached schools", () => {
    const snap = computeAnalytics({ selection: sel({ district: "Mukono" }), now: NOW });
    expect(m(snap.metrics, "schoolsReached").breakdown.planned).toBe(5);
    expect(m(snap.metrics, "districtsCovered").value).toBe(1);
    for (const r of m(snap.metrics, "schoolsReached").records) expect(r.district).toBe("Mukono");
  });

  it("district = Kayunga → only Kayunga (1 reached school, 1 teacher, 412 learners)", () => {
    const snap = computeAnalytics({ selection: sel({ district: "Kayunga" }), now: NOW });
    expect(m(snap.metrics, "schoolsReached").breakdown.planned).toBe(1);
    expect(m(snap.metrics, "teachersTrained").value).toBe(1);
    expect(m(snap.metrics, "learnersImpacted").value).toBe(412);
  });

  it("region = Central includes all (both districts are Central)", () => {
    const snap = computeAnalytics({ selection: sel({ region: "Central" }), now: NOW });
    expect(m(snap.metrics, "districtsCovered").value).toBe(2);
  });
});

describe("FY-cycle scoping", () => {
  it("a future FY with no FY-tagged records yields empty reach", () => {
    // FY 2027 cycle tag has no FY2027-tagged source records in the new mocks.
    const snap = computeAnalytics({ selection: sel({ fy: "2025" }), now: NOW });
    // FY2025 cycle: no enrollment/participants tagged FY2025 → reach collapses.
    expect(m(snap.metrics, "teachersTrained").value).toBe(0);
  });
});
