// Geography source-of-truth integrity.
//
// Locks the invariants that make @/lib/geography safe to rely on app-wide:
//   • every district resolves to exactly one region; no dupes
//   • id ↔ name ↔ slug round-trip
//   • the canonical count is exactly 136 (Central 26 / East 37 / North 38 / West 35)
//   • every legacy alias resolves; resolveDistrictId is idempotent
//   • every staff / partner-scope / school district is a known canonical district
//   • each school's region is DERIVED from its district (never hand-typed)

import { describe, expect, it } from "vitest";
import {
  DISTRICTS,
  ALL_DISTRICTS,
  TOTAL_DISTRICT_COUNT,
  districtCountByRegion,
  regionForDistrict,
  districtById,
  districtByName,
  districtBySlug,
  districtIdFor,
  isKnownDistrictId,
  LEGACY_DISTRICT_ID_ALIASES,
  resolveDistrictId,
  normalizeRegion,
} from "@/lib/geography";
import { STAFF_PROFILES } from "@/lib/funds/budget/staff-district";
import { partnerScopes } from "@/lib/partner/partner-mock";
import { schoolsMock } from "@/lib/schools-mock";

describe("district registry integrity", () => {
  it("has exactly 136 districts and the count agrees across structures", () => {
    expect(TOTAL_DISTRICT_COUNT).toBe(136);
    expect(ALL_DISTRICTS.length).toBe(136);
    expect(DISTRICTS.length).toBe(136);
    const counts = districtCountByRegion();
    expect(counts.Central).toBe(26);
    expect(counts.East).toBe(37);
    expect(counts.North).toBe(38);
    expect(counts.West).toBe(35);
    expect(counts.Central + counts.East + counts.North + counts.West).toBe(136);
  });

  it("every district resolves to exactly one region", () => {
    for (const name of ALL_DISTRICTS) {
      expect(regionForDistrict(name), `region for ${name}`).toBeDefined();
    }
  });

  it("has no duplicate district names, ids, or slugs", () => {
    const names = DISTRICTS.map((d) => d.name);
    const ids = DISTRICTS.map((d) => d.id);
    const slugs = DISTRICTS.map((d) => d.slug);
    expect(new Set(names).size).toBe(names.length);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("round-trips id ↔ name ↔ slug", () => {
    for (const d of DISTRICTS) {
      expect(districtById(d.id)?.name).toBe(d.name);
      expect(districtByName(d.name)?.id).toBe(d.id);
      expect(districtBySlug(d.slug)?.id).toBe(d.id);
      expect(districtIdFor(d.name)).toBe(d.id);
    }
  });
});

describe("legacy alias resolution", () => {
  it("every legacy alias maps to a known canonical id", () => {
    for (const [legacy, canonical] of Object.entries(LEGACY_DISTRICT_ID_ALIASES)) {
      expect(isKnownDistrictId(canonical), `${legacy} → ${canonical}`).toBe(true);
    }
  });

  it("resolveDistrictId handles legacy codes, names, and is idempotent on canonical ids", () => {
    expect(resolveDistrictId("DIST-MBL")).toBe(districtIdFor("Mbale"));
    expect(resolveDistrictId("DST-KITGUM")).toBe(districtIdFor("Kitgum"));
    expect(resolveDistrictId("Kampala")).toBe(districtIdFor("Kampala"));
    const canonical = districtIdFor("Gulu");
    expect(resolveDistrictId(canonical)).toBe(canonical);
    expect(resolveDistrictId(resolveDistrictId("DIST-GUL"))).toBe(canonical);
  });

  it("normalizes long-form / sub-region names onto canonical keys", () => {
    expect(normalizeRegion("Eastern")).toBe("East");
    expect(normalizeRegion("Northern")).toBe("North");
    expect(normalizeRegion("West Nile")).toBe("North");
    expect(normalizeRegion("TBD")).toBeUndefined();
  });
});

describe("mock layers use canonical districts", () => {
  it("every staff profile district resolves to a known canonical district", () => {
    for (const s of STAFF_PROFILES) {
      if (s.primaryDistrictId !== null) {
        expect(isKnownDistrictId(s.primaryDistrictId), `${s.staffName} primary`).toBe(true);
      }
      for (const d of s.assignedDistricts) {
        expect(isKnownDistrictId(d.districtId), `${s.staffName} → ${d.districtId}`).toBe(true);
      }
    }
  });

  it("every partner-scope district is a known canonical district", () => {
    for (const scope of partnerScopes) {
      for (const id of scope.districtIds) {
        expect(isKnownDistrictId(id), `${scope.id} → ${id}`).toBe(true);
      }
    }
  });

  it("every school has a real district and a region DERIVED from it", () => {
    for (const school of schoolsMock) {
      expect(isKnownDistrictId(school.districtId), `${school.schoolId} districtId`).toBe(true);
      expect(districtByName(school.district)?.id).toBe(school.districtId);
      expect(school.region).toBe(regionForDistrict(school.district));
    }
  });
});
