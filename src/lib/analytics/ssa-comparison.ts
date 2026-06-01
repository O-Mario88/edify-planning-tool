// SSA performance comparison — by segment, role-gated, multi-dimensional.
//
// Core and Client SSA are viewed SEPARATELY (segment is a filter, never an axis)
// — we do NOT benchmark core against client. Within a segment, SSA average can
// be compared by FY, district, region, CCEO, cluster, or intervention. The
// dimensions a role may compare by are gated by `ssaDimensionsForRole`.
// Pure & client-safe.

import { historyFor, SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import { getAnalyticsSchools } from "./school-directory";
import { schoolInGeoScope } from "./scope";
import { endYearForDate, fyLabelForEndYear } from "@/lib/fy/fy-core";
import type { FilterSelection } from "@/lib/filters/types";

export type SsaDimension = "fy" | "district" | "region" | "cceo" | "cluster" | "intervention";
export type SsaSegment = "core" | "client";

export type SsaComparisonRow = {
  group: string;
  avgScore: number;
  schoolCount: number;
};

export type SsaComparison = {
  segment: SsaSegment;
  dimension: SsaDimension;
  rows: SsaComparisonRow[];
};

export const SSA_DIMENSION_LABEL: Record<SsaDimension, string> = {
  fy: "By FY",
  district: "By District",
  region: "By Region",
  cceo: "By CCEO",
  cluster: "By Cluster",
  intervention: "By Intervention",
};

// Role gating: CCEO compares within their own scope (no cross-CCEO/region);
// leadership (PL/CD/RVP) + IA may compare by CCEO/region.
const ROLE_DIMENSIONS: Record<string, SsaDimension[]> = {
  CCEO: ["district", "cluster", "intervention", "fy"],
  CountryProgramLead: ["cceo", "region", "district", "cluster", "intervention", "fy"],
  CountryDirector: ["cceo", "region", "district", "cluster", "intervention", "fy"],
  RVP: ["cceo", "region", "district", "intervention", "fy"],
  ImpactAssessment: ["region", "district", "intervention", "fy"],
};

export function ssaDimensionsForRole(role: string): SsaDimension[] {
  return ROLE_DIMENSIONS[role] ?? ["district", "intervention", "fy"];
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function computeSsaComparison(opts: {
  segment: SsaSegment;
  dimension: SsaDimension;
  selection: Pick<FilterSelection, "region" | "district" | "cluster">;
}): SsaComparison {
  const { segment, dimension, selection } = opts;
  const schools = getAnalyticsSchools().filter(
    (s) => s.segment === segment && schoolInGeoScope(s.schoolId, selection),
  );

  // By intervention: average each of the 8 areas across the segment's latest SSA.
  if (dimension === "intervention") {
    const totals = new Map<string, { sum: number; n: number }>();
    for (const s of schools) {
      const rec = historyFor(s.schoolId)[0];
      if (!rec) continue;
      for (const sc of rec.scores) {
        const t = totals.get(sc.intervention) ?? { sum: 0, n: 0 };
        t.sum += sc.score; t.n += 1; totals.set(sc.intervention, t);
      }
    }
    const rows = (SSA_INTERVENTIONS as readonly string[])
      .map((a) => { const t = totals.get(a); return { group: a, avgScore: t && t.n ? round1(t.sum / t.n) : 0, schoolCount: t?.n ?? 0 }; })
      .filter((r) => r.schoolCount > 0);
    return { segment, dimension, rows };
  }

  // By FY: group ALL SSA records (the trajectory) by their FY.
  if (dimension === "fy") {
    const byFy = new Map<string, { sum: number; n: number; schools: Set<string> }>();
    for (const s of schools) {
      for (const rec of historyFor(s.schoolId)) {
        const fy = fyLabelForEndYear(endYearForDate(rec.ssaDate));
        const t = byFy.get(fy) ?? { sum: 0, n: 0, schools: new Set<string>() };
        t.sum += rec.averageScore; t.n += 1; t.schools.add(s.schoolId); byFy.set(fy, t);
      }
    }
    const rows = [...byFy.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([fy, t]) => ({ group: fy, avgScore: round1(t.sum / t.n), schoolCount: t.schools.size }));
    return { segment, dimension, rows };
  }

  // By district / region / cceo / cluster: latest SSA per school, grouped.
  const attr = (s: (typeof schools)[number]): string =>
    dimension === "district" ? s.district
    : dimension === "region" ? (s.region ?? "—")
    : dimension === "cceo" ? s.assignedCceo
    : (s.clusterName ?? "—");
  const byGroup = new Map<string, { sum: number; n: number }>();
  for (const s of schools) {
    const rec = historyFor(s.schoolId)[0];
    if (!rec) continue;
    const k = attr(s);
    const t = byGroup.get(k) ?? { sum: 0, n: 0 };
    t.sum += rec.averageScore; t.n += 1; byGroup.set(k, t);
  }
  const rows = [...byGroup.entries()]
    .map(([g, t]) => ({ group: g, avgScore: round1(t.sum / t.n), schoolCount: t.n }))
    .sort((a, b) => b.avgScore - a.avgScore);
  return { segment, dimension, rows };
}
