// Canonical district registry — one stable record per Ugandan district.
//
// Built programmatically from `DISTRICTS_BY_REGION` (the single name table),
// so there is exactly ONE place district names live. Everything that needs an
// id, slug, or region for a district derives it from here.
//
// District ID format: `UG-D-<SLUG>` (uppercased, hyphen-collapsed name).
// Human-readable, stable, derivable from the name, and greppably distinct
// from the legacy `DIST-`/`DST-` codes (see ./aliases).

import {
  DISTRICTS_BY_REGION,
  UGANDA_REGIONS,
  type UgandaRegion,
} from "@/lib/uganda-districts";
import { REGION_ID_BY_KEY, type RegionId } from "./regions";

export type DistrictId = string; // `UG-D-<SLUG>`

export type DistrictRecord = {
  id: DistrictId;
  name: string;
  /** Kebab-lower URL slug, e.g. "madi-okollo". */
  slug: string;
  regionId: RegionId;
  region: UgandaRegion;
  countryCode: "UG";
  isActive: boolean;
};

/** URL-safe kebab slug for a district name. */
export function districtSlug(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Deterministic canonical id for a district name. */
export function districtIdFor(name: string): DistrictId {
  return `UG-D-${districtSlug(name).toUpperCase()}`;
}

export const DISTRICTS: DistrictRecord[] = UGANDA_REGIONS.flatMap((region) =>
  DISTRICTS_BY_REGION[region].map((name) => ({
    id: districtIdFor(name),
    name,
    slug: districtSlug(name),
    regionId: REGION_ID_BY_KEY[region],
    region,
    countryCode: "UG" as const,
    isActive: true,
  })),
);

const BY_ID = new Map(DISTRICTS.map((d) => [d.id, d]));
const BY_NAME = new Map(DISTRICTS.map((d) => [d.name.toLowerCase(), d]));
const BY_SLUG = new Map(DISTRICTS.map((d) => [d.slug, d]));

export function districtById(id: string): DistrictRecord | undefined {
  return BY_ID.get(id);
}

export function districtByName(name: string): DistrictRecord | undefined {
  if (!name) return undefined;
  return BY_NAME.get(name.trim().toLowerCase());
}

export function districtBySlug(slug: string): DistrictRecord | undefined {
  return BY_SLUG.get(slug);
}

export function isKnownDistrictId(id: string): boolean {
  return BY_ID.has(id);
}

/** District name for an id (or the raw value if unknown — safe for display). */
export function districtNameOf(idOrName: string): string {
  return BY_ID.get(idOrName)?.name ?? districtByName(idOrName)?.name ?? idOrName;
}
