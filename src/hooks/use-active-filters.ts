"use client";

// useActiveFilters — the READ side of the shared filter system. Any card,
// chart, table, or recommendation reads the active selection from the URL
// (written by HeaderFilterBar / useFilterBar) and scopes its data by it.
// This is what makes "the filters control the data" true across the app:
// one source of truth (the URL), one reader.
//
// Mirrors the URL key map in hooks/use-filter-bar.ts (kept in sync — the
// keys are stable + shareable).

import { useSearchParams } from "next/navigation";
import {
  ALL_SENTINEL,
  type FilterKey,
  type FilterSelection,
} from "@/lib/filters/types";

const URL_KEYS: Record<FilterKey, string> = {
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

/** True when a filter dimension has a real (non-"All") value selected. */
export function isFilterActive(value: string | undefined): boolean {
  return !!value && value !== ALL_SENTINEL;
}

/** Read the current filter selection from the URL. FY/Quarter still read
 *  ALL_SENTINEL here when absent — consumers that need the active FY
 *  should fall back to the FY ledger's newest entry. */
export function useActiveFilters(): FilterSelection {
  const params = useSearchParams();
  const get = (k: FilterKey): string => params.get(URL_KEYS[k]) ?? ALL_SENTINEL;
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
