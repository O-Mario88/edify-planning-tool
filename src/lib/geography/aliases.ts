// Legacy district-code compatibility.
//
// Before the canonical `UG-D-*` scheme, two mock layers invented their own
// district codes: `DIST-*` (staff-district.ts) and `DST-*` (partner-mock.ts).
// Those mocks have been migrated to canonical ids, but this alias table is the
// safety seam: any stray legacy code still resolves to the right district.

import {
  districtIdFor,
  districtByName,
  isKnownDistrictId,
  type DistrictId,
} from "./districts";

export const LEGACY_DISTRICT_ID_ALIASES: Record<string, DistrictId> = {
  // ── staff-district.ts (DIST-*) ──
  "DIST-MBL": districtIdFor("Mbale"),
  "DIST-TRR": districtIdFor("Tororo"),
  "DIST-SRT": districtIdFor("Soroti"),
  "DIST-JNJ": districtIdFor("Jinja"),
  "DIST-IGA": districtIdFor("Iganga"),
  "DIST-GUL": districtIdFor("Gulu"),
  "DIST-KTG": districtIdFor("Kitgum"),
  "DIST-LIR": districtIdFor("Lira"),
  "DIST-PDR": districtIdFor("Pader"),
  "DIST-LMW": districtIdFor("Lamwo"),
  "DIST-AGG": districtIdFor("Agago"),
  "DIST-MBR": districtIdFor("Mbarara"),
  "DIST-BSH": districtIdFor("Bushenyi"),
  "DIST-KBR": districtIdFor("Kabarole"),
  "DIST-HOI": districtIdFor("Hoima"),
  "DIST-KLA": districtIdFor("Kampala"),
  "DIST-WAK": districtIdFor("Wakiso"),
  "DIST-MUK": districtIdFor("Mukono"),
  "DIST-ARU": districtIdFor("Arua"),
  "DIST-NEB": districtIdFor("Nebbi"),
  // ── partner-mock.ts (DST-*) ──
  "DST-KITGUM": districtIdFor("Kitgum"),
  "DST-LAMWO": districtIdFor("Lamwo"),
  "DST-GULU": districtIdFor("Gulu"),
  "DST-MBALE": districtIdFor("Mbale"),
  "DST-SIRONKO": districtIdFor("Sironko"),
};

/**
 * Resolve any district reference — a legacy code, a bare district name, or an
 * already-canonical id — to the canonical `UG-D-*` id. Idempotent on canonical
 * ids. Returns the input unchanged when it can't be resolved (non-throwing, so
 * callers can detect drift without crashing).
 */
export function resolveDistrictId(raw: string): string {
  if (!raw) return raw;
  const alias = LEGACY_DISTRICT_ID_ALIASES[raw];
  if (alias) return alias;
  if (isKnownDistrictId(raw)) return raw;
  const byName = districtByName(raw);
  if (byName) return byName.id;
  return raw;
}
