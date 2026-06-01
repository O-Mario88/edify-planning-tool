// Region IDs, display labels, and long-form-name normalisation.
//
// The raw region keys ("North" | "East" | "West" | "Central") live in
// `@/lib/uganda-districts`. This module adds the stable region IDs and the
// human display labels ("Northern Region" …) the UI shows, plus a normaliser
// that folds the long-form / legacy region names used in some mock layers
// ("Eastern", "West Nile", …) back onto the canonical keys.

import { UGANDA_REGIONS, type UgandaRegion } from "@/lib/uganda-districts";

export type RegionId = "R-CENTRAL" | "R-EAST" | "R-NORTH" | "R-WEST";

export type RegionRecord = {
  id: RegionId;
  /** Canonical short key — the value used across the data layer. */
  key: UgandaRegion;
  /** Display label, e.g. "Central Region". */
  label: string;
  countryCode: "UG";
};

export const REGION_ID_BY_KEY: Record<UgandaRegion, RegionId> = {
  Central: "R-CENTRAL",
  East: "R-EAST",
  North: "R-NORTH",
  West: "R-WEST",
};

export const REGION_LABEL_BY_KEY: Record<UgandaRegion, string> = {
  Central: "Central Region",
  East: "Eastern Region",
  North: "Northern Region",
  West: "Western Region",
};

export const REGIONS: RegionRecord[] = UGANDA_REGIONS.map((key) => ({
  id: REGION_ID_BY_KEY[key],
  key,
  label: REGION_LABEL_BY_KEY[key],
  countryCode: "UG" as const,
}));

export function regionLabel(region: UgandaRegion): string {
  return REGION_LABEL_BY_KEY[region];
}

export function regionIdForKey(region: UgandaRegion): RegionId {
  return REGION_ID_BY_KEY[region];
}

// Long-form / legacy region names → canonical key. West Nile, Acholi,
// Karamoja and Mid-North are sub-regions that roll up into the Northern
// region in this 4-region model.
const REGION_ALIASES: Record<string, UgandaRegion> = {
  central: "Central",
  east: "East",
  eastern: "East",
  north: "North",
  northern: "North",
  "west nile": "North",
  acholi: "North",
  "mid-north": "North",
  karamoja: "North",
  lango: "North",
  west: "West",
  western: "West",
};

/** Normalise any region string (long-form or legacy) to the canonical key. */
export function normalizeRegion(raw: string | null | undefined): UgandaRegion | undefined {
  if (!raw) return undefined;
  return REGION_ALIASES[raw.trim().toLowerCase()];
}
