// Parish / village layer.
//
// Absorbs the village catalogue that was hard-coded in
// `src/lib/planning/school-address.ts` (VILLAGES_BY_DISTRICT). In Uganda's
// administrative chain the leaf is Parish → Village; the demo only carries a
// representative village set per district. Production reads the full table.
// Lookups are keyed by canonical district name.

export const VILLAGES_BY_DISTRICT: Record<string, string[]> = {
  Kayunga: ["Bbaale Town", "Galiraaya Centre", "Kasawo", "Nazigo", "Kayonza", "Wabwoko"],
  Mukono: ["Ntenjeru", "Nakifuma Hill", "Nsumba", "Kasangati", "Goma", "Najjembe"],
  Pader: ["Atanga Hill", "Pajule", "Lapul", "Acholibur", "Awere", "Adagnyeko"],
  Kitgum: ["Lakwana", "Pakwelo", "Okidi", "Padibe", "Lokung", "Mucwini"],
  Lamwo: ["Madi Opei", "Agoro", "Palabek", "Ngomoromo", "Lokung", "Padibe East"],
  Agago: ["Patongo", "Wol", "Adilang", "Lapono", "Lira Palwo", "Omot"],
  Gulu: ["Layibi", "Pece", "Bardege", "Laroo", "Bungatira", "Awach"],
  Omoro: ["Bobi", "Lakwana Hill", "Odek", "Lalogi", "Koro", "Ongako"],
  Kampala: ["Naguru", "Bukoto", "Kamwokya", "Nakawa", "Ntinda", "Bugolobi"],
  Wakiso: ["Kira", "Nansana", "Kasangati", "Wakiso TC", "Nabweru", "Gombe"],
  Hoima: ["Kabaale", "Buhanika", "Bujumbura", "Kigorobya", "Buseruka", "Kahoora"],
  Mbarara: ["Nyakayojo", "Kakoba", "Kakiika", "Biharwe", "Kashare", "Rwentondo"],
};

/** Representative villages for a district. Empty for districts without demo data. */
export function villagesOf(district: string): string[] {
  return VILLAGES_BY_DISTRICT[district] ?? [];
}

/**
 * Parishes for a sub-county. The demo has no parish→sub-county table yet, so
 * this returns an empty list — present so callers can adopt the parish layer
 * without a signature change once real data lands.
 */
export function parishesOf(_subCountyId: string): string[] {
  return [];
}
