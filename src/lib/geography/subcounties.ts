// Sub-county layer.
//
// The full district -> sub-county register, mapped from the official Uganda
// General Elections 2015-2016 sub-county statistics (see subcounties-data.ts,
// auto-generated from the source PDF). 106 districts, ~1,300 sub-counties.
// Keyed by canonical district name; the shape and lookups are unchanged.

import {
  districtByName,
  districtSlug,
  type DistrictId,
} from "./districts";
import { SUBCOUNTY_NAMES_BY_DISTRICT } from "./subcounties-data";

export type SubCounty = {
  id: string; // `UG-SC-<district-slug>-<subcounty-slug>`
  name: string;
  districtId: DistrictId;
  districtName: string;
};

function subCountyId(districtName: string, subCountyName: string): string {
  return `UG-SC-${districtSlug(districtName)}-${districtSlug(subCountyName)}`;
}

export const SUBCOUNTIES: SubCounty[] = Object.entries(SUBCOUNTY_NAMES_BY_DISTRICT).flatMap(
  ([districtName, names]) => {
    const d = districtByName(districtName);
    return names.map((name) => ({
      id: subCountyId(districtName, name),
      name,
      // Fall back to a derived id if the district name ever drifts — keeps the
      // sub-county addressable rather than dropping it.
      districtId: (d?.id ?? `UG-D-${districtSlug(districtName).toUpperCase()}`) as DistrictId,
      districtName,
    }));
  },
);

const BY_DISTRICT_NAME = new Map<string, SubCounty[]>();
const BY_DISTRICT_ID = new Map<string, SubCounty[]>();
for (const sc of SUBCOUNTIES) {
  const byName = BY_DISTRICT_NAME.get(sc.districtName.toLowerCase()) ?? [];
  byName.push(sc);
  BY_DISTRICT_NAME.set(sc.districtName.toLowerCase(), byName);
  const byId = BY_DISTRICT_ID.get(sc.districtId) ?? [];
  byId.push(sc);
  BY_DISTRICT_ID.set(sc.districtId, byId);
}

/** Sub-counties for a district, addressed by canonical id OR district name
 *  (case-insensitive on the name). */
export function subCountiesOf(districtIdOrName: string): SubCounty[] {
  if (!districtIdOrName) return [];
  const key = districtIdOrName.toLowerCase();
  return (
    BY_DISTRICT_ID.get(districtIdOrName) ??
    BY_DISTRICT_NAME.get(key) ??
    BY_DISTRICT_NAME.get((districtByName(districtIdOrName)?.name ?? "").toLowerCase()) ??
    []
  );
}
