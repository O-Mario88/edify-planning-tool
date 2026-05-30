"use client";

// Analytics filter bar — controlled hook.
//
// Owns the live selection across all 10 dimensions, persists every
// non-default value to the URL query string, and enforces the
// dependent-reset rules (region change clears district / cluster /
// CCEO / partner that no longer match; FY change resets quarter and
// reclamps anything that was tied to the prior FY).
//
// The hook is render-only: the page reads `selection`, the bar reads
// `narrowedScope`, and `setFilter(key, value)` is the only mutator.

import { useCallback, useMemo } from "react";
import { useUrlFilters } from "@/hooks/use-url-state";
import {
  ALL_SENTINEL,
  type FilterKey,
  type FilterOption,
  type FilterScope,
  type FilterSelection,
} from "@/lib/filters/types";

// URL query keys — short, stable, shareable.
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

// Which child filters get cleared when a parent changes. Mirrors
// scope-service's `parentKey` relationships.
const CASCADE: Partial<Record<FilterKey, FilterKey[]>> = {
  fy:       ["quarter"],
  region:   ["district", "cluster", "cceo", "partner"],
  district: ["cluster", "cceo", "partner"],
  cluster:  ["cceo", "partner"],
  cceo:     ["partner"],
};

// Narrow a child option list to those whose parentKey matches a given
// parent id. Options without a parentKey (the "All …" sentinel + any
// program-defined static options) always pass through. Array-form
// parentKey matches if the parent is anywhere in the set.
function narrowByParent(
  options: FilterOption[],
  parentId: string | undefined,
): FilterOption[] {
  if (!parentId || parentId === ALL_SENTINEL) return options;
  return options.filter((o) => {
    if (o.id === ALL_SENTINEL || !o.parentKey) return true;
    if (Array.isArray(o.parentKey)) return o.parentKey.includes(parentId);
    return o.parentKey === parentId;
  });
}

export type UseFilterBarReturn = {
  selection: FilterSelection;
  narrowedScope: FilterScope;
  setFilter: (key: FilterKey, value: string) => void;
  resetAll: () => void;
};

export function useFilterBar(scope: FilterScope): UseFilterBarReturn {
  // Build the spec for useUrlFilters from the scope's first option.
  // FY defaults to the newest (FY ledger is sorted newest-first); all
  // other keys default to ALL_SENTINEL.
  const spec = useMemo(() => {
    const defaultFy = scope.fy.options[0]?.id ?? ALL_SENTINEL;
    return {
      [URL_KEYS.fy]:       { defaultValue: defaultFy },
      [URL_KEYS.quarter]:  { defaultValue: ALL_SENTINEL },
      [URL_KEYS.region]:   { defaultValue: ALL_SENTINEL },
      [URL_KEYS.district]: { defaultValue: ALL_SENTINEL },
      [URL_KEYS.cluster]:  { defaultValue: ALL_SENTINEL },
      [URL_KEYS.cceo]:     { defaultValue: ALL_SENTINEL },
      [URL_KEYS.partner]:  { defaultValue: ALL_SENTINEL },
      [URL_KEYS.package]:  { defaultValue: ALL_SENTINEL },
      [URL_KEYS.ssa]:      { defaultValue: ALL_SENTINEL },
      [URL_KEYS.champion]: { defaultValue: ALL_SENTINEL },
    };
  }, [scope.fy.options]);

  const [urlValues, setUrlValues, resetUrlValues] = useUrlFilters(spec);

  // Map URL keys back to FilterKey + clamp values to options that
  // actually exist in the current scope (a shared link from another
  // user might point to a region you can't see).
  const selection: FilterSelection = useMemo(() => {
    const clamp = (key: FilterKey, raw: string): string => {
      const opts = scope[key].options;
      return opts.some((o) => o.id === raw) ? raw : (opts[0]?.id ?? ALL_SENTINEL);
    };
    return {
      fy:       clamp("fy",       urlValues[URL_KEYS.fy]),
      quarter:  clamp("quarter",  urlValues[URL_KEYS.quarter]),
      region:   clamp("region",   urlValues[URL_KEYS.region]),
      district: clamp("district", urlValues[URL_KEYS.district]),
      cluster:  clamp("cluster",  urlValues[URL_KEYS.cluster]),
      cceo:     clamp("cceo",     urlValues[URL_KEYS.cceo]),
      partner:  clamp("partner",  urlValues[URL_KEYS.partner]),
      package:  clamp("package",  urlValues[URL_KEYS.package]),
      ssa:      clamp("ssa",      urlValues[URL_KEYS.ssa]),
      champion: clamp("champion", urlValues[URL_KEYS.champion]),
    };
  }, [scope, urlValues]);

  // Narrowed scope — child options filtered by their resolved parent.
  // Order matters: region narrows district, then district narrows
  // cluster, then cluster narrows cceo, etc.
  const narrowedScope: FilterScope = useMemo(() => {
    const districtNarrowed = narrowByParent(
      scope.district.options,
      selection.region,
    );
    const clusterNarrowed = narrowByParent(
      scope.cluster.options,
      selection.district,
    );
    return {
      ...scope,
      district: { ...scope.district, options: districtNarrowed },
      cluster:  { ...scope.cluster,  options: clusterNarrowed  },
    };
  }, [scope, selection.region, selection.district]);

  const setFilter = useCallback(
    (key: FilterKey, value: string) => {
      const patch: Record<string, string> = { [URL_KEYS[key]]: value };
      // Cascade: any descendant whose currently-selected value is no
      // longer valid under the new parent resets to ALL_SENTINEL. We
      // reset unconditionally — checking validity per-child would need
      // the new narrowed options, which depend on the patch we're about
      // to send. Cheap and predictable.
      const dependents = CASCADE[key] ?? [];
      for (const dep of dependents) {
        patch[URL_KEYS[dep]] = ALL_SENTINEL;
      }
      setUrlValues(patch);
    },
    [setUrlValues],
  );

  return { selection, narrowedScope, setFilter, resetAll: resetUrlValues };
}
