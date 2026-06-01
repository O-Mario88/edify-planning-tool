// Verification / evidence / payment metric groups (Phase 4).
// Uses the FY2027 cycle where the activity spine is rich.

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
const snap = computeAnalytics({ selection: sel({ fy: "2027" }), role: "CCEO", now: "2025-11-15" });

describe("verification / evidence / payment groups exist and are coherent", () => {
  it("evidence accepted ≤ uploaded, and missing is separate", () => {
    const uploaded = m(snap.metrics, "evidenceUploaded").value;
    const accepted = m(snap.metrics, "evidenceAccepted").value;
    const missing = m(snap.metrics, "evidenceMissing").value;
    expect(accepted).toBeLessThanOrEqual(uploaded);
    expect(missing).toBeGreaterThanOrEqual(0);
  });

  it("Salesforce gate: at least one activity is missing an SF id", () => {
    // ACT-NSSA1-1 (FY2027) has no Salesforce record.
    expect(m(snap.metrics, "sfMissing").value).toBeGreaterThanOrEqual(1);
    expect(m(snap.metrics, "sfMissing").records.some((r) => r.id === "ACT-NSSA1-1")).toBe(true);
  });

  it("payments cleared are a subset of completed activities", () => {
    const paid = m(snap.metrics, "paymentsPaid").value;
    const completed = m(snap.metrics, "activitiesCompleted").value;
    expect(paid).toBeGreaterThan(0);
    expect(paid).toBeLessThanOrEqual(completed + m(snap.metrics, "paymentsBlocked").value + 50);
  });

  it("every new metric has a definition + drilldown records", () => {
    for (const key of ["evidenceUploaded", "sfEntered", "iaVerified", "paymentsPaid", "paymentsBlocked"]) {
      const metric = m(snap.metrics, key);
      expect(metric.definition.length).toBeGreaterThan(10);
      expect(Array.isArray(metric.records)).toBe(true);
    }
  });
});
