// Filter → data apply utilities.

import { describe, expect, it } from "vitest";
import {
  buildDateRangeFromFilters,
  applyDateScope,
  applyGeographyScope,
  geoParamsFromSelection,
} from "@/lib/filters/apply-filters";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";

function sel(over: Partial<FilterSelection>): FilterSelection {
  return {
    fy: ALL_SENTINEL, quarter: ALL_SENTINEL, region: ALL_SENTINEL, district: ALL_SENTINEL,
    cluster: ALL_SENTINEL, cceo: ALL_SENTINEL, partner: ALL_SENTINEL, package: ALL_SENTINEL,
    ssa: ALL_SENTINEL, champion: ALL_SENTINEL, ...over,
  };
}

describe("buildDateRangeFromFilters", () => {
  it("FY only → full FY range", () => {
    expect(buildDateRangeFromFilters({ fy: "2026", quarter: ALL_SENTINEL }, "2025-11-15"))
      .toEqual({ startDate: "2025-10-01", endDate: "2026-09-30" });
  });
  it("FY + Q2 → quarter range", () => {
    expect(buildDateRangeFromFilters({ fy: "2026", quarter: "Q2" }, "2025-11-15"))
      .toEqual({ startDate: "2026-01-01", endDate: "2026-03-31" });
  });
  it("no FY → active FY", () => {
    expect(buildDateRangeFromFilters({ fy: ALL_SENTINEL, quarter: ALL_SENTINEL }, "2025-11-15"))
      .toEqual({ startDate: "2025-10-01", endDate: "2026-09-30" });
  });
});

describe("applyDateScope", () => {
  const rows = [{ d: "2026-02-01" }, { d: "2025-11-01" }, { d: undefined }];
  it("keeps in-range, excludes undated when a range is active", () => {
    const r = applyDateScope(rows, { startDate: "2026-01-01", endDate: "2026-03-31" }, (x) => x.d);
    expect(r).toEqual([{ d: "2026-02-01" }]);
  });
  it("no range → passthrough", () => {
    expect(applyDateScope(rows, undefined, (x) => x.d).length).toBe(3);
  });
});

describe("applyGeographyScope", () => {
  const rows = [
    { district: "Kampala", region: "Central", clusterId: "C1" },
    { district: "Jinja", region: "East", clusterId: "C2" },
    { district: "Gulu", region: "North", clusterId: "C3" },
  ];
  const acc = {
    district: (r: (typeof rows)[number]) => r.district,
    region: (r: (typeof rows)[number]) => r.region,
    cluster: (r: (typeof rows)[number]) => r.clusterId,
  };

  it("region filter", () => {
    expect(applyGeographyScope(rows, sel({ region: "Central" }), acc).map((r) => r.district)).toEqual(["Kampala"]);
  });
  it("district filter", () => {
    expect(applyGeographyScope(rows, sel({ district: "Jinja" }), acc).map((r) => r.district)).toEqual(["Jinja"]);
  });
  it("cluster filter", () => {
    expect(applyGeographyScope(rows, sel({ cluster: "C3" }), acc).map((r) => r.district)).toEqual(["Gulu"]);
  });
  it("All → passthrough", () => {
    expect(applyGeographyScope(rows, sel({}), acc).length).toBe(3);
  });
  it("backfills region from district when no region accessor", () => {
    const accNoRegion = { district: (r: (typeof rows)[number]) => r.district };
    expect(applyGeographyScope(rows, sel({ region: "East" }), accNoRegion).map((r) => r.district)).toEqual(["Jinja"]);
  });
});

// The server-side bridge: a page maps its URL selection to the backend geo
// params and the backend narrows the WHOLE page (strip + charts + tables), not
// just the rows already on the client. This locks the mapping is faithful and
// drops the "no filter" sentinel so an unfiltered page stays unfiltered.
describe("geoParamsFromSelection", () => {
  it("drops __all__ — an unfiltered selection yields no params", () => {
    expect(geoParamsFromSelection(sel({}))).toEqual({});
  });
  it("passes a real district through (backend resolves the name)", () => {
    expect(geoParamsFromSelection(sel({ district: "Gulu" }))).toEqual({ district: "Gulu" });
  });
  it("passes region + cluster, omitting the unselected district", () => {
    expect(geoParamsFromSelection(sel({ region: "northern", cluster: "clu_x" }))).toEqual({
      region: "northern",
      cluster: "clu_x",
    });
  });
  it("ignores non-geography selections (fy/cceo/ssa never leak into geo params)", () => {
    expect(geoParamsFromSelection(sel({ fy: "2026", cceo: "staff1", ssa: "weak", district: "Mbale" }))).toEqual({
      district: "Mbale",
    });
  });
});
