// Sub-county layer.
//
// Consolidates the sub-county lists that were previously hard-coded inside
// `AddToClusterDrawer.tsx` (DISTRICT_SUBCOUNTIES), keyed by canonical district
// name. Demo-grade and intentionally partial — production reads the full
// administrative-units table; the shape and lookups stay identical.

import {
  districtByName,
  districtSlug,
  type DistrictId,
} from "./districts";

export type SubCounty = {
  id: string; // `UG-SC-<district-slug>-<subcounty-slug>`
  name: string;
  districtId: DistrictId;
  districtName: string;
};

const SUBCOUNTY_NAMES_BY_DISTRICT: Record<string, string[]> = {
  Kayunga: ["Bbaale", "Galiraaya", "Kayunga Central", "Kayunga Town", "Kitimbwa"],
  Mukono: ["Mukono Central", "Ntenjeru", "Nakifuma", "Kireka", "Nsumba", "Bukoto", "Namilyango"],
  Pader: ["Atanga", "Laguti", "Pader Town", "Lapul"],
  Kitgum: ["Kitgum Central", "Mucwini", "Orom", "Lagoro"],
  Lamwo: ["Padibe East", "Padibe West", "Palabek Gem", "Lokung"],
  Agago: ["Agago Hub", "Patongo", "Kalongo", "Lira-Palwo"],
  Gulu: ["Gulu Municipality", "Bardege", "Pece", "Layibi"],
  Wakiso: ["Wakiso Central", "Nansana", "Kira", "Kasanje"],
  Kampala: ["Kampala Central", "Nakawa", "Rubaga", "Makindye"],
  Mbarara: ["Mbarara East", "Kakoba", "Nyamitanga", "Biharwe"],
  Hoima: ["Hoima Central", "Buseruka", "Kigorobya", "Kyabigambire"],
  Omoro: ["Omoro West", "Bobi", "Lakwana", "Tochi"],
  // School-hub districts not previously covered, added so every hub district
  // the planning surface touches has at least a demo sub-county set.
  Jinja: ["Jinja Central", "Mafubira", "Budondo", "Buwenge"],
  Iganga: ["Iganga Central", "Nakigo", "Nambale", "Bulamagi"],
  Arua: ["Arua Hill", "Dadamu", "Adumi", "Vurra"],
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
  const byName = BY_DISTRICT_NAME.get(sc.districtName) ?? [];
  byName.push(sc);
  BY_DISTRICT_NAME.set(sc.districtName, byName);
  const byId = BY_DISTRICT_ID.get(sc.districtId) ?? [];
  byId.push(sc);
  BY_DISTRICT_ID.set(sc.districtId, byId);
}

/** Sub-counties for a district, addressed by canonical id OR district name. */
export function subCountiesOf(districtIdOrName: string): SubCounty[] {
  if (!districtIdOrName) return [];
  return (
    BY_DISTRICT_ID.get(districtIdOrName) ??
    BY_DISTRICT_NAME.get(districtIdOrName) ??
    BY_DISTRICT_NAME.get(districtByName(districtIdOrName)?.name ?? "") ??
    []
  );
}
