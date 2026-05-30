// School address + contact helpers.
//
// The planning page lists schools by "District · SubCounty" — too
// shallow for the field staff and partners who actually have to drive
// to the school and reach the head teacher. This module composes the
// full 4-level postal address (District, Subcounty, Parish, Village)
// and a primary contact (head teacher name + phone) for any
// school-shaped object.
//
// In the demo, village + contact are deterministically derived from
// the school name + district so the same school always shows the same
// address and contact across screens (no jitter between page loads).
// Production swaps the village table for the real Ugandan administrative
// map and reads contacts from the school registry; the callers don't
// change — `fullAddressOf(school)` and `primaryContactOf(school)` are
// stable across both worlds.

// ────────── Minimal shape any school must satisfy ──────────

export type AddressableSchool = {
  schoolName: string;
  district:   string;
  subCounty:  string;
  parish?:    string;
};

// ────────── Village catalogue per district ──────────
//
// Realistic Ugandan village/trading-centre names grouped by district.
// Production reads these from the administrative-units table; here
// we keep a small representative set so the demo addresses look
// plausible to a Ugandan reader.

const VILLAGES_BY_DISTRICT: Record<string, string[]> = {
  Kayunga: ["Bbaale Town",   "Galiraaya Centre", "Kasawo",   "Nazigo",      "Kayonza",    "Wabwoko"],
  Mukono:  ["Ntenjeru",       "Nakifuma Hill",   "Nsumba",   "Kasangati",   "Goma",       "Najjembe"],
  Pader:   ["Atanga Hill",    "Pajule",          "Lapul",    "Acholibur",   "Awere",      "Adagnyeko"],
  Kitgum:  ["Lakwana",        "Pakwelo",         "Okidi",    "Padibe",      "Lokung",     "Mucwini"],
  Lamwo:   ["Madi Opei",      "Agoro",           "Palabek",  "Ngomoromo",   "Lokung",     "Padibe East"],
  Agago:   ["Patongo",        "Wol",             "Adilang",  "Lapono",      "Lira Palwo", "Omot"],
  Gulu:    ["Layibi",         "Pece",            "Bardege",  "Laroo",       "Bungatira",  "Awach"],
  Omoro:   ["Bobi",           "Lakwana Hill",    "Odek",     "Lalogi",      "Koro",       "Ongako"],
  Kampala: ["Naguru",         "Bukoto",          "Kamwokya", "Nakawa",      "Ntinda",     "Bugolobi"],
  Wakiso:  ["Kira",           "Nansana",         "Kasangati","Wakiso TC",   "Nabweru",    "Gombe"],
  Hoima:   ["Kabaale",        "Buhanika",        "Bujumbura","Kigorobya",   "Buseruka",   "Kahoora"],
  Mbarara: ["Nyakayojo",      "Kakoba",          "Kakiika",  "Biharwe",     "Kashare",    "Rwentondo"],
  // Sentinel — falls through to "Trading Centre" for any unknown district.
};

const HEAD_TEACHER_NAMES = [
  "Daniel Mwangi",     "Grace Atim",          "John Mubiru",     "Rose Nakato",
  "Peter Wamala",      "Sarah Namutebi",      "Brian Okello",    "Aisha Nansubuga",
  "Moses Wakabi",      "Esther Naluwu",       "Joseph Otim",     "Margaret Kintu",
  "Patrick Lumumba",   "Mary Auma",           "Robert Sserwanga","Beatrice Akello",
  "Henry Wanyama",     "Florence Nabasa",     "Samuel Lubega",   "Joyce Achieng",
];

// ────────── Deterministic hashing ──────────
//
// Cheap, non-crypto, deterministic-across-runs hash of a string to a
// non-negative integer. Used to pick a village + contact for a school
// without persisting the value — the same school name always lands on
// the same row.

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

// ────────── Public helpers ──────────

/** Village name for a school. Falls back to "Trading Centre" for unknown districts. */
export function villageOf(school: AddressableSchool): string {
  const list = VILLAGES_BY_DISTRICT[school.district];
  if (!list || list.length === 0) return "Trading Centre";
  return list[hash(school.schoolName) % list.length];
}

/**
 * Full 4-level postal address: "District, Subcounty, Parish, Village".
 * Matches the addressing convention used on the school registry —
 * staff and partners can plug this string straight into a GPS app or
 * a phone-call brief without further composition.
 */
export function fullAddressOf(school: AddressableSchool): string {
  const village = villageOf(school);
  const parts = [
    school.district,
    school.subCounty,
    school.parish ?? school.subCounty,
    village,
  ];
  return parts.join(", ");
}

export type SchoolContact = {
  name:  string;
  phone: string;
};

/**
 * Head-teacher contact for a school: name + phone in Ugandan mobile
 * format (`+256 7XX XXX XXX`). Deterministic per school.
 */
export function primaryContactOf(school: AddressableSchool): SchoolContact {
  const h    = hash(school.schoolName + ":" + school.district);
  const name = HEAD_TEACHER_NAMES[h % HEAD_TEACHER_NAMES.length];
  // Ugandan mobile: +256 7XX XXX XXX. Use the hash to fill the last
  // 9 digits so the number is stable per school.
  const digits = (h % 1_000_000_000).toString().padStart(9, "0");
  const phone  = `+256 7${digits.slice(0, 1)}${digits.slice(1, 2)} ${digits.slice(2, 5)} ${digits.slice(5, 8)}`;
  return { name, phone };
}
