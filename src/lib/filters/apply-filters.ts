// Filter → data apply utilities (PURE, client-safe).
//
// The READ side of "every page obeys the filters": a card/list reads the
// active selection (useActiveFilters) then scopes its rows through these.
// Geography + date scope are pure and run client-side; ROLE scope stays
// server-side (it needs DemoUser + schoolsMock via scope-service) — pages get
// already-role-scoped rows from a server component, then apply geo/date here.

import {
  generateFinancialYears,
  quarterDateRangeForFy,
} from "@/lib/fy/fy-core";
import { regionForDistrict } from "@/lib/geography";
import { ALL_SENTINEL, type FilterSelection } from "./types";

export type DateRange = { startDate: string; endDate: string };

function isReal(value: string | undefined): boolean {
  return !!value && value !== ALL_SENTINEL;
}

// URL query keys — MUST stay in sync with hooks/use-active-filters.ts
// (the client reader) and hooks/use-filter-bar.ts (the writer).
const URL_KEYS: Record<keyof FilterSelection, string> = {
  fy:       "fy",
  quarter:  "q",
  region:   "region",
  district: "district",
  cluster:  "cluster",
  cceo:     "cceo",
  partner:  "partner",
  package:  "pkg",
  ssa:      "ssa",
  champion: "champ",
};

/**
 * Server-side counterpart of `useActiveFilters()`: read the filter
 * selection from a page's awaited `searchParams`. Lets server components
 * scope their data by the same URL the HeaderFilterBar writes.
 */
export function selectionFromSearchParams(
  sp: Record<string, string | string[] | undefined>,
): FilterSelection {
  const get = (k: keyof FilterSelection): string => {
    const v = sp[URL_KEYS[k]];
    const s = Array.isArray(v) ? v[0] : v;
    return s && s.length > 0 ? s : ALL_SENTINEL;
  };
  return {
    fy:       get("fy"),
    quarter:  get("quarter"),
    region:   get("region"),
    district: get("district"),
    cluster:  get("cluster"),
    cceo:     get("cceo"),
    partner:  get("partner"),
    package:  get("package"),
    ssa:      get("ssa"),
    champion: get("champion"),
  };
}

/**
 * Map the URL filter selection to the backend geography filter params.
 * The backend resolves these by NAME (district)/key (region)/cuid (cluster) via
 * relation filters — so a server component can pass `geoParamsFromSelection(sel)`
 * straight into the analytics surfaces and the WHOLE page narrows server-side
 * (strip + charts + tables), not just the rows visible on the page. `__all__`
 * and empty values are dropped so an unfiltered page stays unfiltered.
 */
export function geoParamsFromSelection(
  selection: Pick<FilterSelection, "region" | "district" | "cluster">,
): { region?: string; district?: string; cluster?: string } {
  const out: { region?: string; district?: string; cluster?: string } = {};
  if (isReal(selection.region)) out.region = selection.region;
  if (isReal(selection.district)) out.district = selection.district;
  if (isReal(selection.cluster)) out.cluster = selection.cluster;
  return out;
}

/**
 * Resolve the selected FY (+ optional quarter) to an ISO date range.
 * FY only → the full FY window. FY + quarter → that quarter's window.
 * Falls back to the active FY when no FY is selected.
 */
export function buildDateRangeFromFilters(
  selection: Pick<FilterSelection, "fy" | "quarter">,
  now?: string,
): DateRange {
  const years = generateFinancialYears(now);
  const fy =
    (isReal(selection.fy) ? years.find((y) => y.id === selection.fy) : undefined) ??
    years.find((y) => y.status === "Active") ??
    years[0];

  if (isReal(selection.quarter)) {
    const q = quarterDateRangeForFy(fy, selection.quarter);
    if (q) return q;
  }
  return { startDate: fy.startDate, endDate: fy.endDate };
}

/**
 * Keep rows whose date (via `dateAccessor`) falls within `range`. Rows with no
 * date are EXCLUDED when a range is active (they can't be placed in the period).
 */
export function applyDateScope<T>(
  rows: T[],
  range: DateRange | undefined,
  dateAccessor: (row: T) => string | undefined,
): T[] {
  if (!range) return rows;
  return rows.filter((r) => {
    const d = dateAccessor(r);
    if (!d) return false;
    return d >= range.startDate && d <= range.endDate;
  });
}

export type GeographyAccessors<T> = {
  /** Row's canonical region key ("Central"/"East"/…). Optional if `district` is given. */
  region?: (row: T) => string | undefined;
  /** Row's canonical district NAME. */
  district?: (row: T) => string | undefined;
  /** Row's cluster id. */
  cluster?: (row: T) => string | undefined;
};

/**
 * Scope rows by the selected region / district / cluster. Each dimension is
 * skipped when its selection is "All". Region is backfilled from district via
 * the geography source of truth when the row only exposes a district.
 */
export function applyGeographyScope<T>(
  rows: T[],
  selection: Pick<FilterSelection, "region" | "district" | "cluster">,
  accessors: GeographyAccessors<T>,
): T[] {
  const wantRegion = isReal(selection.region);
  const wantDistrict = isReal(selection.district);
  const wantCluster = isReal(selection.cluster);
  if (!wantRegion && !wantDistrict && !wantCluster) return rows;

  return rows.filter((row) => {
    if (wantDistrict && accessors.district) {
      if (accessors.district(row) !== selection.district) return false;
    }
    if (wantRegion) {
      const direct = accessors.region?.(row);
      const reg = direct ?? (accessors.district ? regionForDistrict(accessors.district(row) ?? "") : undefined);
      if (reg !== selection.region) return false;
    }
    if (wantCluster && accessors.cluster) {
      if (accessors.cluster(row) !== selection.cluster) return false;
    }
    return true;
  });
}
