// Analytics school directory — the single schoolId → geography join.
//
// Phase 1 canonical school universe = the GAP-* activity spine
// (planning-gaps-mock), the only namespace with activities + geography + an
// FY/operationalCycle. Projects SchoolGap[] into a normalized AnalyticsSchool
// so the engine never reaches into gap-mock internals. Region is derived from
// the geography source of truth. Pure & client-safe.

import { schoolGaps } from "@/lib/planning/planning-gaps-mock";
import { regionForDistrict, type UgandaRegion } from "@/lib/geography";

export type SchoolCategory = "client" | "core" | "other";

export type AnalyticsSchool = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: UgandaRegion | undefined;
  subCounty?: string;
  parish?: string;
  clusterName?: string;
  segment: SchoolCategory;
  assignedCceo: string;
  assignedPartner?: string;
};

// GAP ids encode a rough segment: -NC- (no cluster) schools are treated as
// client; the rest mix core/client. Kept deterministic so tests are stable.
function segmentFor(id: string): SchoolCategory {
  if (id.includes("-NTR-")) return "core"; // training-rich → core track
  return "client";
}

const SCHOOLS: AnalyticsSchool[] = schoolGaps.map((g) => ({
  schoolId: g.id,
  schoolName: g.schoolName,
  district: g.district,
  region: regionForDistrict(g.district),
  subCounty: g.subCounty,
  parish: g.parish,
  clusterName: g.clusterName,
  segment: segmentFor(g.id),
  assignedCceo: g.assignedCceo,
  assignedPartner: g.assignedPartner,
}));

const BY_ID = new Map(SCHOOLS.map((s) => [s.schoolId, s]));

export function getAnalyticsSchools(): AnalyticsSchool[] {
  return SCHOOLS;
}

export function analyticsSchoolById(schoolId: string): AnalyticsSchool | undefined {
  return BY_ID.get(schoolId);
}

/** Geography for a schoolId, for scope accessors. */
export function geoForSchool(schoolId: string): {
  district?: string;
  region?: string;
  clusterName?: string;
} {
  const s = BY_ID.get(schoolId);
  return { district: s?.district, region: s?.region, clusterName: s?.clusterName };
}
