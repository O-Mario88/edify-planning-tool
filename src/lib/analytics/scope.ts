// Analytics scoping — resolve the selected filters to a record predicate.
//
// FY is scoped by the record's operationalCycle TAG ("FY2026"), matched to the
// selected FY id ("2026"); quarter narrows by date within that cycle; geography
// (region/district/cluster) resolves through the school directory. Pure.

import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";
import { buildDateRangeFromFilters, type DateRange } from "@/lib/filters/apply-filters";
import { generateFinancialYears, activeFinancialYear } from "@/lib/fy/fy-core";
import { engineNowIso } from "@/lib/clock";
import { regionForDistrict } from "@/lib/geography";
import { geoForSchool } from "./school-directory";

export function isReal(value: string | undefined): boolean {
  return !!value && value !== ALL_SENTINEL;
}

/** Selected FY id ("2026"); falls back to the active FY. */
export function selectedFyId(selection: Pick<FilterSelection, "fy">, now = engineNowIso()): string {
  if (isReal(selection.fy)) return selection.fy;
  return activeFinancialYear(generateFinancialYears(now)).id;
}

/** Operational-cycle tag for an FY id — "2026" → "FY2026". */
export function cycleTagForFy(fyId: string): string {
  return `FY${fyId}`;
}

export function selectedCycleTag(selection: Pick<FilterSelection, "fy">, now = engineNowIso()): string {
  return cycleTagForFy(selectedFyId(selection, now));
}

/** Quarter date window within the selected FY, or undefined for full-FY. */
export function selectedQuarterRange(
  selection: Pick<FilterSelection, "fy" | "quarter">,
  now = engineNowIso(),
): DateRange | undefined {
  if (!isReal(selection.quarter)) return undefined;
  return buildDateRangeFromFilters({ fy: selectedFyId(selection, now), quarter: selection.quarter }, now);
}

/** True when a school passes the region/district/cluster selection. */
export function schoolInGeoScope(
  schoolId: string,
  selection: Pick<FilterSelection, "region" | "district" | "cluster">,
): boolean {
  const wantDistrict = isReal(selection.district);
  const wantRegion = isReal(selection.region);
  const wantCluster = isReal(selection.cluster);
  if (!wantDistrict && !wantRegion && !wantCluster) return true;

  const g = geoForSchool(schoolId);
  if (wantDistrict && g.district !== selection.district) return false;
  if (wantRegion) {
    const reg = g.region ?? regionForDistrict(g.district ?? "");
    if (reg !== selection.region) return false;
  }
  // Cluster options today come from a different school universe; best-effort
  // name match (cluster-id↔name reconciliation is a later phase).
  if (wantCluster && g.clusterName !== selection.cluster) return false;
  return true;
}

/** True when an ISO date sits in the quarter window (or no window active). */
export function dateInRange(date: string | undefined, range: DateRange | undefined): boolean {
  if (!range) return true;
  if (!date) return false;
  return date >= range.startDate && date <= range.endDate;
}
