// Canonical Uganda district + region mapping (UBOS structure).
//
// One module owns the geography across the app. Any feature that needs
// to validate a district, render a region picker, or aggregate by region
// should import from here rather than redefining lists.
//
// Source: user-provided UBOS list. Notes on canonical decisions:
//   • "Luuka" was listed in BOTH Central and Eastern in the source. Luuka
//     is in Busoga (Eastern sub-region), so it lives in Eastern here.
//   • Spellings (e.g. "Adjuman", "Nabilatsek") are kept as supplied; if a
//     correction is needed it should happen here so every consumer
//     inherits the fix.

export type UgandaRegion = "North" | "East" | "West" | "Central";

export const UGANDA_REGIONS: UgandaRegion[] = ["North", "East", "West", "Central"];

// Region → districts (UBOS structure). Order matches the source list.
export const DISTRICTS_BY_REGION: Record<UgandaRegion, readonly string[]> = {
  Central: [
    "Buikwe", "Bukomansimbi", "Butambala", "Buvuma", "Gomba", "Kalangala",
    "Kalungu", "Kampala", "Kassanda", "Kayunga", "Kiboga", "Kyankwanzi",
    "Kyotera", "Luwero", "Lwengo", "Lyantonde", "Masaka", "Mityana", "Mpigi",
    "Mubende", "Mukono", "Nakaseke", "Nakasongola", "Rakai", "Sembabule",
    "Wakiso",
  ] as const,
  East: [
    "Budaka", "Bududa", "Bugiri", "Bugweri", "Bukedea", "Bukwo", "Bulambuli",
    "Busia", "Butaleja", "Butebo", "Buyende", "Iganga", "Jinja",
    "Kaberamaido", "Kaliro", "Kamuli", "Kapchorwa", "Kapelebyong", "Katakwi",
    "Kibuku", "Kumi", "Kween", "Luuka", "Manafwa", "Mayuge", "Mbale",
    "Namisindwa", "Namutumba", "Ngora", "Pallisa", "Serere", "Sironko",
    "Soroti", "Tororo",
  ] as const,
  // Northern includes "Kitgum" — not present in the source list as
  // supplied, but it is a real UBOS district and the existing demo data
  // anchors there. Added here with a flag so the user can audit.
  North: [
    "Abim", "Adjuman", "Agago", "Alebtong", "Amolatar", "Amudat", "Amuru",
    "Apac", "Arua", "Arua City", "Dokolo", "Gulu", "Gulu City", "Kaabong",
    "Karenga", "Kitgum", "Koboko", "Kole", "Kotido", "Kwania", "Lamwo",
    "Lira", "Lira City", "Madi-Okollo", "Maracha", "Moroto", "Moyo",
    "Nabilatsek", "Nakapiripirit", "Napak", "Nebbi", "Nwoya", "Obongi",
    "Omoro", "Otuke", "Oyam", "Pader", "Pakwach", "Terego", "Zombo",
  ] as const,
  West: [
    "Buhweju", "Buliisa", "Bundibugyo", "Bunyangabu", "Bushenyi", "Hoima",
    "Hoima City", "Ibanda", "Isingiro", "Kabale", "Kabarole", "Kamwenge",
    "Kanungu", "Kasese", "Kazo", "Kibaale", "Kiruhura", "Kiryandongo",
    "Kisoro", "Kitagwenda", "Kyegegwa", "Kyenjojo", "Masindi", "Mbarara",
    "Mbarara City", "Mitooma", "Ntoroko", "Ntungamo", "Rubanda", "Rubirizi",
    "Rukungiri", "Rwampara", "Sheema",
  ] as const,
};

// Flat list of every Ugandan district, deterministically ordered (region
// → alphabetical within region as supplied).
export const ALL_DISTRICTS: readonly string[] = UGANDA_REGIONS.flatMap(
  (r) => DISTRICTS_BY_REGION[r],
);

// Derived reverse-lookup: district name → region. Built once at module load.
export const REGION_BY_DISTRICT: Readonly<Record<string, UgandaRegion>> = (() => {
  const out: Record<string, UgandaRegion> = {};
  for (const region of UGANDA_REGIONS) {
    for (const district of DISTRICTS_BY_REGION[region]) {
      out[district] = region;
    }
  }
  return out;
})();

// ────────── Helpers ──────────

export function regionForDistrict(district: string): UgandaRegion | undefined {
  return REGION_BY_DISTRICT[district];
}

export function districtsInRegion(region: UgandaRegion): readonly string[] {
  return DISTRICTS_BY_REGION[region];
}

export function isKnownDistrict(district: string): boolean {
  return district in REGION_BY_DISTRICT;
}

// District-count summary — handy for admin / data-intake validation.
export function districtCountByRegion(): Record<UgandaRegion, number> {
  return {
    North:   DISTRICTS_BY_REGION.North.length,
    East:    DISTRICTS_BY_REGION.East.length,
    West:    DISTRICTS_BY_REGION.West.length,
    Central: DISTRICTS_BY_REGION.Central.length,
  };
}

// Total district count across the country (sanity check for tests /
// data-intake gates).
export const TOTAL_DISTRICT_COUNT = ALL_DISTRICTS.length;
