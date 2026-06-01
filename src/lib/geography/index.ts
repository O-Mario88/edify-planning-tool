// Uganda geography — the single source of truth.
//
// Import from `@/lib/geography` for anything geographic: validating a
// district, rendering a region/district picker, resolving a legacy code,
// listing sub-counties, or aggregating by region. This package wraps the raw
// name↔region table in `@/lib/uganda-districts` and adds IDs, display labels,
// sub-counties, and a village/parish layer. Do NOT redefine district lists
// elsewhere — derive from here.
//
// Pure and client-safe (no `server-only`), so client components can import it.

// Raw name table + region helpers (pass-through, unchanged API).
export {
  type UgandaRegion,
  UGANDA_REGIONS,
  DISTRICTS_BY_REGION,
  ALL_DISTRICTS,
  REGION_BY_DISTRICT,
  regionForDistrict,
  districtsInRegion,
  isKnownDistrict,
  districtCountByRegion,
  TOTAL_DISTRICT_COUNT,
} from "@/lib/uganda-districts";

// Regions — ids, labels, normalisation.
export {
  type RegionId,
  type RegionRecord,
  REGIONS,
  REGION_ID_BY_KEY,
  REGION_LABEL_BY_KEY,
  regionLabel,
  regionIdForKey,
  normalizeRegion,
} from "./regions";

// Districts — canonical registry + lookups.
export {
  type DistrictId,
  type DistrictRecord,
  DISTRICTS,
  districtSlug,
  districtIdFor,
  districtById,
  districtByName,
  districtBySlug,
  districtNameOf,
  isKnownDistrictId,
} from "./districts";

// Legacy-code compatibility.
export { LEGACY_DISTRICT_ID_ALIASES, resolveDistrictId } from "./aliases";

// Sub-counties.
export { type SubCounty, SUBCOUNTIES, subCountiesOf } from "./subcounties";

// Parish / village layer.
export { VILLAGES_BY_DISTRICT, villagesOf, parishesOf } from "./parishes";

import { regionIdForKey } from "./regions";
import { districtByName } from "./districts";
import type { UgandaRegion } from "@/lib/uganda-districts";

/** Canonical region id for a district name (via the source-of-truth lookup). */
export function regionIdFor(district: string): string | undefined {
  const d = districtByName(district);
  return d ? regionIdForKey(d.region as UgandaRegion) : undefined;
}
