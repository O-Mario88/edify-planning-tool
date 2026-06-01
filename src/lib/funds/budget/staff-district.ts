// Staff identity + district classification. Primary district = home district
// (no accommodation); everything else is secondary (transport + full meals +
// accommodation by default). Budget engine cannot compute for a staff without
// primaryDistrictId.
//
// District ids are the canonical `UG-D-*` ids from `@/lib/geography`. The raw
// profiles below are authored with the legacy `DIST-*` codes for readability;
// they're normalised to canonical ids (and canonical region keys) on export so
// the whole app shares one district-id scheme.

import { resolveDistrictId, normalizeRegion } from "@/lib/geography";

export type DistrictType = "PRIMARY" | "SECONDARY";

export type StaffProfile = {
  staffId: string;
  staffName: string;
  role: "CCEO" | "PartnerOfficer" | "ProgramLead" | "Trainer";
  team: string;
  region: string;
  primaryDistrictId: string | null;
  primaryDistrictName: string | null;
  assignedDistricts: Array<{ districtId: string; districtName: string }>;
};

export function classifyDistrict(
  staff: StaffProfile,
  activityDistrictId: string,
): DistrictType {
  if (
    staff.primaryDistrictId !== null &&
    staff.primaryDistrictId === activityDistrictId
  ) {
    return "PRIMARY";
  }
  return "SECONDARY";
}

export function isBudgetable(staff: StaffProfile): boolean {
  return staff.primaryDistrictId !== null;
}

export function nonBudgetableReason(staff: StaffProfile): string | null {
  if (staff.primaryDistrictId === null) {
    return "Staff has no primary district assigned. Budget engine cannot allocate accommodation/transport defaults until a home district is set.";
  }
  return null;
}

export function secondaryDistrictsOf(
  staff: StaffProfile,
): Array<{ districtId: string; districtName: string }> {
  if (staff.primaryDistrictId === null) {
    return staff.assignedDistricts.slice();
  }
  return staff.assignedDistricts.filter(
    (d) => d.districtId !== staff.primaryDistrictId,
  );
}

const RAW_STAFF_PROFILES: StaffProfile[] = [
  // East team (5)
  {
    staffId: "STF-PC-001",
    staffName: "Patrick Ochieng",
    role: "ProgramLead",
    team: "East",
    region: "Eastern",
    primaryDistrictId: "DIST-MBL",
    primaryDistrictName: "Mbale",
    assignedDistricts: [
      { districtId: "DIST-MBL", districtName: "Mbale" },
      { districtId: "DIST-TRR", districtName: "Tororo" },
      { districtId: "DIST-SRT", districtName: "Soroti" },
    ],
  },
  {
    staffId: "STF-MO-002",
    staffName: "Margaret Opio",
    role: "PartnerOfficer",
    team: "East",
    region: "Eastern",
    primaryDistrictId: "DIST-TRR",
    primaryDistrictName: "Tororo",
    assignedDistricts: [
      { districtId: "DIST-TRR", districtName: "Tororo" },
      { districtId: "DIST-MBL", districtName: "Mbale" },
      { districtId: "DIST-JNJ", districtName: "Jinja" },
    ],
  },
  {
    staffId: "STF-TR-003",
    staffName: "Timothy Wanyama",
    role: "Trainer",
    team: "East",
    region: "Eastern",
    primaryDistrictId: "DIST-JNJ",
    primaryDistrictName: "Jinja",
    assignedDistricts: [
      { districtId: "DIST-JNJ", districtName: "Jinja" },
      { districtId: "DIST-IGA", districtName: "Iganga" },
      { districtId: "DIST-MBL", districtName: "Mbale" },
    ],
  },
  {
    staffId: "STF-PO-004",
    staffName: "Phoebe Nakato",
    role: "PartnerOfficer",
    team: "East",
    region: "Eastern",
    primaryDistrictId: "DIST-IGA",
    primaryDistrictName: "Iganga",
    assignedDistricts: [
      { districtId: "DIST-IGA", districtName: "Iganga" },
      { districtId: "DIST-JNJ", districtName: "Jinja" },
    ],
  },
  {
    staffId: "STF-TR-005",
    staffName: "Stephen Egunyu",
    role: "Trainer",
    team: "East",
    region: "Eastern",
    primaryDistrictId: "DIST-SRT",
    primaryDistrictName: "Soroti",
    assignedDistricts: [
      { districtId: "DIST-SRT", districtName: "Soroti" },
      { districtId: "DIST-MBL", districtName: "Mbale" },
      { districtId: "DIST-TRR", districtName: "Tororo" },
    ],
  },

  // North team (3)
  {
    staffId: "STF-PL-006",
    staffName: "Grace Aciro",
    role: "ProgramLead",
    team: "North",
    region: "Northern",
    primaryDistrictId: "DIST-GUL",
    primaryDistrictName: "Gulu",
    assignedDistricts: [
      { districtId: "DIST-GUL", districtName: "Gulu" },
      { districtId: "DIST-KTG", districtName: "Kitgum" },
      { districtId: "DIST-LIR", districtName: "Lira" },
    ],
  },
  {
    staffId: "STF-PO-007",
    staffName: "Joseph Okello",
    role: "PartnerOfficer",
    team: "North",
    region: "Northern",
    primaryDistrictId: "DIST-KTG",
    primaryDistrictName: "Kitgum",
    assignedDistricts: [
      { districtId: "DIST-KTG", districtName: "Kitgum" },
      { districtId: "DIST-PDR", districtName: "Pader" },
      { districtId: "DIST-LMW", districtName: "Lamwo" },
      { districtId: "DIST-AGG", districtName: "Agago" },
    ],
  },
  {
    staffId: "STF-TR-008",
    staffName: "Betty Akello",
    role: "Trainer",
    team: "North",
    region: "Northern",
    primaryDistrictId: "DIST-LIR",
    primaryDistrictName: "Lira",
    assignedDistricts: [
      { districtId: "DIST-LIR", districtName: "Lira" },
      { districtId: "DIST-GUL", districtName: "Gulu" },
      { districtId: "DIST-AGG", districtName: "Agago" },
    ],
  },

  // West team (4)
  {
    staffId: "STF-PL-009",
    staffName: "Innocent Tumusiime",
    role: "ProgramLead",
    team: "West",
    region: "Western",
    primaryDistrictId: "DIST-MBR",
    primaryDistrictName: "Mbarara",
    assignedDistricts: [
      { districtId: "DIST-MBR", districtName: "Mbarara" },
      { districtId: "DIST-BSH", districtName: "Bushenyi" },
      { districtId: "DIST-KBR", districtName: "Kabarole" },
    ],
  },
  {
    staffId: "STF-PO-010",
    staffName: "Sarah Kyomuhendo",
    role: "PartnerOfficer",
    team: "West",
    region: "Western",
    primaryDistrictId: "DIST-BSH",
    primaryDistrictName: "Bushenyi",
    assignedDistricts: [
      { districtId: "DIST-BSH", districtName: "Bushenyi" },
      { districtId: "DIST-MBR", districtName: "Mbarara" },
      { districtId: "DIST-HOI", districtName: "Hoima" },
    ],
  },
  {
    staffId: "STF-TR-011",
    staffName: "Edgar Byaruhanga",
    role: "Trainer",
    team: "West",
    region: "Western",
    primaryDistrictId: "DIST-KBR",
    primaryDistrictName: "Kabarole",
    assignedDistricts: [
      { districtId: "DIST-KBR", districtName: "Kabarole" },
      { districtId: "DIST-HOI", districtName: "Hoima" },
      { districtId: "DIST-MBR", districtName: "Mbarara" },
    ],
  },
  {
    staffId: "STF-TR-012",
    staffName: "Doreen Kabugho",
    role: "Trainer",
    team: "West",
    region: "Western",
    primaryDistrictId: "DIST-HOI",
    primaryDistrictName: "Hoima",
    assignedDistricts: [
      { districtId: "DIST-HOI", districtName: "Hoima" },
      { districtId: "DIST-KBR", districtName: "Kabarole" },
    ],
  },

  // Central team (3)
  {
    staffId: "STF-CC-013",
    staffName: "Ronald Ssempala",
    role: "CCEO",
    team: "Central",
    region: "Central",
    primaryDistrictId: "DIST-KLA",
    primaryDistrictName: "Kampala",
    assignedDistricts: [
      { districtId: "DIST-KLA", districtName: "Kampala" },
      { districtId: "DIST-WAK", districtName: "Wakiso" },
      { districtId: "DIST-MUK", districtName: "Mukono" },
    ],
  },
  {
    staffId: "STF-PL-014",
    staffName: "Linda Namuli",
    role: "ProgramLead",
    team: "Central",
    region: "Central",
    primaryDistrictId: "DIST-WAK",
    primaryDistrictName: "Wakiso",
    assignedDistricts: [
      { districtId: "DIST-WAK", districtName: "Wakiso" },
      { districtId: "DIST-KLA", districtName: "Kampala" },
      { districtId: "DIST-MUK", districtName: "Mukono" },
    ],
  },
  {
    staffId: "STF-PO-015",
    staffName: "Brian Mukasa",
    role: "PartnerOfficer",
    team: "Central",
    region: "Central",
    primaryDistrictId: "DIST-MUK",
    primaryDistrictName: "Mukono",
    assignedDistricts: [
      { districtId: "DIST-MUK", districtName: "Mukono" },
      { districtId: "DIST-KLA", districtName: "Kampala" },
      { districtId: "DIST-JNJ", districtName: "Jinja" },
    ],
  },

  // West Nile team
  {
    staffId: "STF-PO-016",
    staffName: "Faith Anyango",
    role: "PartnerOfficer",
    team: "West Nile",
    region: "West Nile",
    primaryDistrictId: "DIST-ARU",
    primaryDistrictName: "Arua",
    assignedDistricts: [
      { districtId: "DIST-ARU", districtName: "Arua" },
      { districtId: "DIST-NEB", districtName: "Nebbi" },
      { districtId: "DIST-GUL", districtName: "Gulu" },
    ],
  },

  // Acholi sub-team
  {
    staffId: "STF-TR-017",
    staffName: "Moses Komakech",
    role: "Trainer",
    team: "Acholi",
    region: "Northern",
    primaryDistrictId: "DIST-PDR",
    primaryDistrictName: "Pader",
    assignedDistricts: [
      { districtId: "DIST-PDR", districtName: "Pader" },
      { districtId: "DIST-LMW", districtName: "Lamwo" },
      { districtId: "DIST-AGG", districtName: "Agago" },
      { districtId: "DIST-KTG", districtName: "Kitgum" },
    ],
  },

  // Demo / unassigned (no primary — blocked budget state)
  {
    staffId: "STF-DEMO-X",
    staffName: "Unassigned Demo Staff",
    role: "Trainer",
    team: "Floating",
    region: "TBD",
    primaryDistrictId: null,
    primaryDistrictName: null,
    assignedDistricts: [
      { districtId: "DIST-NEB", districtName: "Nebbi" },
      { districtId: "DIST-ARU", districtName: "Arua" },
    ],
  },
];

// Normalise the raw profiles onto the canonical district-id scheme + region
// keys. Legacy `DIST-*` codes resolve via the geography alias table; the
// classify/budgetable helpers compare strings, so this swap is transparent.
export const STAFF_PROFILES: StaffProfile[] = RAW_STAFF_PROFILES.map((s) => ({
  ...s,
  region: normalizeRegion(s.region) ?? s.region,
  primaryDistrictId:
    s.primaryDistrictId === null ? null : resolveDistrictId(s.primaryDistrictId),
  assignedDistricts: s.assignedDistricts.map((d) => ({
    districtId: resolveDistrictId(d.districtId),
    districtName: d.districtName,
  })),
}));

export function getStaffProfile(id: string): StaffProfile | undefined {
  return STAFF_PROFILES.find((s) => s.staffId === id);
}
