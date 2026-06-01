// Exam (§18) + MSC (§19) metrics + workflow funnel.

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
const snap = computeAnalytics({ selection: sel(), role: "CCEO", now: "2025-11-15" });

describe("exam analytics", () => {
  it("collected / missing / rate", () => {
    expect(m(snap.metrics, "examResultsCollected").value).toBe(7);
    expect(m(snap.metrics, "examMissing").value).toBe(2);
    expect(m(snap.metrics, "examCollectionRate").value).toBe(78); // 7/9
  });
});

describe("MSC analytics + workflow funnel", () => {
  it("submitted / donor-ready / pending", () => {
    expect(m(snap.metrics, "mscSubmitted").value).toBe(7);
    expect(m(snap.metrics, "mscDonorReady").value).toBe(2);
    expect(m(snap.metrics, "mscPendingReview").value).toBe(1);
  });
  it("funnel is monotonic Submitted ≥ PL Reviewed ≥ Verified ≥ Donor-Ready", () => {
    const counts = snap.mscFunnel.map((s) => s.count);
    expect(counts).toEqual([7, 6, 4, 2]);
    for (let i = 1; i < counts.length; i++) expect(counts[i]).toBeLessThanOrEqual(counts[i - 1]);
  });
});
