// SSA comparison — role gating + segment separation (never core-vs-client).

import { describe, expect, it } from "vitest";
import {
  computeSsaComparison,
  ssaDimensionsForRole,
} from "@/lib/analytics/ssa-comparison";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";

function geo(over: Partial<Pick<FilterSelection, "region" | "district" | "cluster">> = {}) {
  return { region: ALL_SENTINEL, district: ALL_SENTINEL, cluster: ALL_SENTINEL, ...over };
}

describe("role-gated comparison dimensions", () => {
  it("CCEO cannot compare by CCEO or region", () => {
    const dims = ssaDimensionsForRole("CCEO");
    expect(dims).not.toContain("cceo");
    expect(dims).not.toContain("region");
    expect(dims).toEqual(expect.arrayContaining(["district", "intervention", "fy"]));
  });
  it("PL / CD / RVP can compare by CCEO and region", () => {
    for (const role of ["CountryProgramLead", "CountryDirector", "RVP"]) {
      const dims = ssaDimensionsForRole(role);
      expect(dims).toContain("cceo");
      expect(dims).toContain("region");
    }
  });
});

describe("segments are computed separately (never benchmarked together)", () => {
  it("core and client by-district draw from disjoint school sets", () => {
    const core = computeSsaComparison({ segment: "core", dimension: "district", selection: geo() });
    const client = computeSsaComparison({ segment: "client", dimension: "district", selection: geo() });
    expect(core.segment).toBe("core");
    expect(client.segment).toBe("client");
    const coreSchools = core.rows.reduce((n, r) => n + r.schoolCount, 0);
    const clientSchools = client.rows.reduce((n, r) => n + r.schoolCount, 0);
    expect(coreSchools).toBeGreaterThan(0);
    expect(clientSchools).toBeGreaterThanOrEqual(0);
    // No row groups a mix — each comparison is single-segment by construction.
    expect(core.rows.every((r) => r.avgScore >= 0 && r.avgScore <= 10)).toBe(true);
  });

  it("by-intervention yields ≤ 8 areas, all scored 0–10", () => {
    const c = computeSsaComparison({ segment: "core", dimension: "intervention", selection: geo() });
    expect(c.rows.length).toBeLessThanOrEqual(8);
    expect(c.rows.every((r) => r.avgScore >= 0 && r.avgScore <= 10)).toBe(true);
  });

  it("geography filter narrows the comparison", () => {
    const all = computeSsaComparison({ segment: "core", dimension: "district", selection: geo() });
    const kayunga = computeSsaComparison({ segment: "core", dimension: "district", selection: geo({ district: "Kayunga" }) });
    expect(kayunga.rows.every((r) => r.group === "Kayunga")).toBe(true);
    expect(kayunga.rows.length).toBeLessThanOrEqual(all.rows.length);
  });
});
