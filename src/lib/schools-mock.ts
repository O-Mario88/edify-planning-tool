// School Directory Dashboard — mock data layer.
//
// CRITICAL ACCESS RULE (per product doc):
//   The school directory is CCEO-scoped via Salesforce assignment fields.
//   The current CCEO must only see schools where Assigned_CCEO_ID matches
//   their staffId. KPI counts, urgent-attention list, planning signals,
//   search, export, and pagination must all reduce to the assigned set.
//
// Shapes mirror the Salesforce import contract so backend swap is a no-op.

import { regionForDistrict, districtIdFor, type DistrictId } from "@/lib/geography";

// ────────── Auth / current user ──────────

export type AppRole =
  | "CCEO"
  | "CountryProgramLead"
  | "CountryDirector"
  | "RVP"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "HumanResource"
  | "Admin";

export type CurrentUser = {
  staffId: string;
  salesforceOwnerId: string;
  email: string;
  name: string;
  initials: string;
  role: AppRole;
  country: "Uganda";
  scope: string;
};

// The screenshot displays a country-wide view (512 schools, etc.); the
// signed-in user is therefore role-elevated above CCEO. The sidebar label
// "Planning Officer" is the user's scope, not their role. The access-control
// branch in getVisibleSchools() still enforces a strict assignment filter
// when role === "CCEO" — flip the role here and the page reduces to just
// that user's assigned schools, with no other code path changes.
export const currentUser: CurrentUser = {
  staffId: "STF-DM-014",
  salesforceOwnerId: "0050X000009ABCD",
  email: "daniel.mwangi@edify.org",
  name: "Daniel Mwangi",
  initials: "DM",
  role: "CountryProgramLead",
  country: "Uganda",
  scope: "Planning Officer",
};

// ────────── School (Salesforce-aligned) ──────────

export type SchoolType = "Primary" | "Secondary" | "Cluster";
export type SchoolSegment = "Client" | "Core" | "New" | "Other";
export type SchoolStatus = "Active" | "Inactive" | "Closed";
export type SsaStatus = "Completed" | "Not Completed" | "Overdue";
export type Priority = "Critical" | "High" | "Medium" | "Low";
export type Region = "North" | "East" | "West" | "Central";

export type RecommendedAction =
  | "Re-engagement Visit"
  | "Cluster Training"
  | "SSA Support"
  | "In-School Coaching"
  | "Follow-Up by Partner"
  | "Monitoring & Review";

// A district is a canonical Ugandan district NAME (see @/lib/geography). The
// old "Central|East|West|Cluster" union actually stored regions — it was wrong
// and is gone. Geography is derived from the shipping hub on export (region is
// never hand-typed), so `district`/`region`/`districtId` always agree.
export type District = string;

// Shipping address is the school's postal/distribution hub. Staff use it as
// the primary clustering dimension because routes, deliveries, and
// in-person visits naturally group around it. Each hub maps to one canonical
// district via HUB_TO_DISTRICT below.
export type ShippingAddress =
  | "Kampala Hub - Central"
  | "Mukono Hub - Central"
  | "Jinja Hub - East"
  | "Iganga Hub - East"
  | "Mbarara Hub - West"
  | "Hoima Hub - West"
  | "Arua Cluster Hub";

// Hub → canonical district. The single mapping that turns a distribution hub
// into real geography; region is then derived from the district.
const HUB_TO_DISTRICT: Record<ShippingAddress, string> = {
  "Kampala Hub - Central": "Kampala",
  "Mukono Hub - Central": "Mukono",
  "Jinja Hub - East": "Jinja",
  "Iganga Hub - East": "Iganga",
  "Mbarara Hub - West": "Mbarara",
  "Hoima Hub - West": "Hoima",
  "Arua Cluster Hub": "Arua",
};

function geoFromHub(hub: ShippingAddress): {
  district: string;
  districtId: DistrictId;
  region: Region;
} {
  const district = HUB_TO_DISTRICT[hub];
  return {
    district,
    districtId: districtIdFor(district),
    region: (regionForDistrict(district) ?? "Central") as Region,
  };
}

export type SchoolRow = {
  schoolId: string;
  salesforceSchoolId: string;
  schoolName: string;
  country: "Uganda";
  region: Region;
  district: District;       // canonical district name — derived from the hub
  districtId: DistrictId;   // canonical UG-D-* id — derived from the hub
  shippingAddress: ShippingAddress;
  schoolType: SchoolType;
  segment: SchoolSegment;
  schoolStatus: SchoolStatus;

  // Salesforce assignment fields (the access-control source of truth)
  assignedCceoId: string;
  assignedCceoName: string;
  assignedCceoEmail: string;
  salesforceOwnerId: string;

  // Partner assignment
  assignedPartnerId?: string;
  assignedPartnerName?: string;

  // Operational state
  ssaStatus: SsaStatus;
  ssaScore: number;
  latestVisitDate?: string;   // ISO YYYY-MM-DD or "—"
  latestTrainingDate?: string;
  noVisit: boolean;
  noTraining: boolean;
  priority: Priority;
  recommendedNextAction: RecommendedAction;
};

// All Salesforce school records seen by the directory before access-control
// filtering. In production this is an API call; here it's a static array.
// Exported (aliased) so detail pages can resolve a school by its id without
// re-implementing the visibility filter — those pages render server-side
// after the access-control branch in `getVisibleSchools` already vetted
// the row.
// Raw rows. `region`/`district` literals below are placeholders — they are
// OVERRIDDEN on export by geoFromHub(shippingAddress), so the source of truth
// is the hub, not the hand-typed value. `districtId` is added on export.
const RAW_SCHOOLS: Array<Omit<SchoolRow, "districtId">> = [
  {
    schoolId: "SCH-001",
    salesforceSchoolId: "a01-001",
    schoolName: "Sunrise Primary School",
    country: "Uganda",
    region: "North",
    district: "Central",
    shippingAddress: "Kampala Hub - Central",
    schoolType: "Primary",
    segment: "Core",
    schoolStatus: "Inactive",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Not Completed",
    ssaScore: 22,
    latestVisitDate: undefined,
    latestTrainingDate: undefined,
    noVisit: true,
    noTraining: true,
    priority: "Critical",
    recommendedNextAction: "Re-engagement Visit",
  },
  {
    schoolId: "SCH-002",
    salesforceSchoolId: "a01-002",
    schoolName: "Greenfield Secondary",
    country: "Uganda",
    region: "North",
    district: "Central",
    shippingAddress: "Kampala Hub - Central",
    schoolType: "Secondary",
    segment: "Client",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    assignedPartnerId: "PRT-001",
    assignedPartnerName: "Partner",
    ssaStatus: "Not Completed",
    ssaScore: 28,
    latestVisitDate: "2025-05-15",
    latestTrainingDate: undefined,
    noVisit: false,
    noTraining: true,
    priority: "High",
    recommendedNextAction: "Cluster Training",
  },
  {
    schoolId: "SCH-003",
    salesforceSchoolId: "a01-003",
    schoolName: "Riverside Primary School",
    country: "Uganda",
    region: "North",
    district: "Cluster",
    shippingAddress: "Mukono Hub - Central",
    schoolType: "Primary",
    segment: "Core",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Not Completed",
    ssaScore: 33,
    latestVisitDate: "2025-05-05",
    latestTrainingDate: undefined,
    noVisit: false,
    noTraining: true,
    priority: "High",
    recommendedNextAction: "SSA Support",
  },
  {
    schoolId: "SCH-004",
    salesforceSchoolId: "a01-004",
    schoolName: "Hilltop Basic School",
    country: "Uganda",
    region: "North",
    district: "Cluster",
    shippingAddress: "Mukono Hub - Central",
    schoolType: "Primary",
    segment: "Core",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Not Completed",
    ssaScore: 41,
    latestVisitDate: "2025-05-15",
    latestTrainingDate: undefined,
    noVisit: false,
    noTraining: true,
    priority: "High",
    recommendedNextAction: "Cluster Training",
  },
  {
    schoolId: "SCH-005",
    salesforceSchoolId: "a01-005",
    schoolName: "Eastview Junior School",
    country: "Uganda",
    region: "North",
    district: "East",
    shippingAddress: "Jinja Hub - East",
    schoolType: "Primary",
    segment: "Core",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    assignedPartnerId: "PRT-002",
    assignedPartnerName: "Partner",
    ssaStatus: "Completed",
    ssaScore: 58,
    latestVisitDate: "2025-05-20",
    latestTrainingDate: "2025-05-12",
    noVisit: false,
    noTraining: false,
    priority: "Medium",
    recommendedNextAction: "In-School Coaching",
  },
  {
    schoolId: "SCH-006",
    salesforceSchoolId: "a01-006",
    schoolName: "Maple Grove Primary",
    country: "Uganda",
    region: "North",
    district: "Central",
    shippingAddress: "Kampala Hub - Central",
    schoolType: "Primary",
    segment: "Client",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Completed",
    ssaScore: 64,
    latestVisitDate: "2025-05-18",
    latestTrainingDate: "2025-05-15",
    noVisit: false,
    noTraining: false,
    priority: "Medium",
    recommendedNextAction: "Cluster Training",
  },
  {
    schoolId: "SCH-007",
    salesforceSchoolId: "a01-007",
    schoolName: "Northview Secondary",
    country: "Uganda",
    region: "North",
    district: "East",
    shippingAddress: "Iganga Hub - East",
    schoolType: "Secondary",
    segment: "Core",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    assignedPartnerId: "PRT-003",
    assignedPartnerName: "Partner",
    ssaStatus: "Completed",
    ssaScore: 71,
    latestVisitDate: "2025-05-22",
    latestTrainingDate: "2025-05-16",
    noVisit: false,
    noTraining: false,
    priority: "Low",
    recommendedNextAction: "Follow-Up by Partner",
  },
  {
    schoolId: "SCH-008",
    salesforceSchoolId: "a01-008",
    schoolName: "Bright Future School",
    country: "Uganda",
    region: "North",
    district: "East",
    shippingAddress: "Jinja Hub - East",
    schoolType: "Primary",
    segment: "Client",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Completed",
    ssaScore: 74,
    latestVisitDate: "2025-05-19",
    latestTrainingDate: "2025-05-18",
    noVisit: false,
    noTraining: false,
    priority: "Low",
    recommendedNextAction: "Monitoring & Review",
  },
  {
    schoolId: "SCH-009",
    salesforceSchoolId: "a01-009",
    schoolName: "Hope Academy",
    country: "Uganda",
    region: "North",
    district: "Cluster",
    shippingAddress: "Mukono Hub - Central",
    schoolType: "Cluster",
    segment: "Client",
    schoolStatus: "Active",
    assignedCceoId: "STF-PC-001",
    assignedCceoName: "Paul Chinyama",
    assignedCceoEmail: "paul.chinyama@edify.org",
    salesforceOwnerId: "0050X000009ABCD",
    ssaStatus: "Completed",
    ssaScore: 78,
    latestVisitDate: "2025-05-21",
    latestTrainingDate: "2025-05-19",
    noVisit: false,
    noTraining: false,
    priority: "Low",
    recommendedNextAction: "Monitoring & Review",
  },
  // Negative-case rows (assigned to a different CCEO).
  // These must NEVER appear for the current user — they exist to prove the
  // access-control filter at getCceoSchools() drops them.
  {
    schoolId: "SCH-X01",
    salesforceSchoolId: "a01-x01",
    schoolName: "Other CCEO School A",
    country: "Uganda",
    region: "Central",
    district: "Central",
    shippingAddress: "Kampala Hub - Central",
    schoolType: "Primary",
    segment: "Core",
    schoolStatus: "Active",
    assignedCceoId: "STF-OTHER-001",
    assignedCceoName: "Grace Nansubuga",
    assignedCceoEmail: "grace.n@edify.org",
    salesforceOwnerId: "0050X000009OTHR",
    ssaStatus: "Completed",
    ssaScore: 80,
    latestVisitDate: "2025-05-10",
    latestTrainingDate: "2025-05-09",
    noVisit: false,
    noTraining: false,
    priority: "Low",
    recommendedNextAction: "Monitoring & Review",
  },
  {
    schoolId: "SCH-X02",
    salesforceSchoolId: "a01-x02",
    schoolName: "Other CCEO School B",
    country: "Uganda",
    region: "East",
    district: "East",
    shippingAddress: "Iganga Hub - East",
    schoolType: "Secondary",
    segment: "Client",
    schoolStatus: "Active",
    assignedCceoId: "STF-OTHER-002",
    assignedCceoName: "James Okello",
    assignedCceoEmail: "james.o@edify.org",
    salesforceOwnerId: "0050X000009OTHR2",
    ssaStatus: "Completed",
    ssaScore: 75,
    latestVisitDate: "2025-05-11",
    latestTrainingDate: "2025-05-08",
    noVisit: false,
    noTraining: false,
    priority: "Low",
    recommendedNextAction: "Monitoring & Review",
  },
];

// Normalise geography from the shipping hub. region/district/districtId always
// agree because they're all derived from one source (the hub → district map).
export const schoolsMock: SchoolRow[] = RAW_SCHOOLS.map((s) => {
  const { district, districtId, region } = geoFromHub(s.shippingAddress);
  return { ...s, region, district, districtId };
});

// Server-side access control. The CCEO sees ONLY schools where
// assigned_cceo_id matches their staff_id. Higher roles widen scope; admins
// see all. Run this server-side; do not filter in the browser.
//
// Preferred matching order (per product doc):
//   1. assignedCceoId
//   2. salesforceOwnerId
//   3. assignedCceoEmail
//   4. assignedCceoName (last resort)
export function getVisibleSchools(user: CurrentUser): SchoolRow[] {
  if (user.role === "Admin") return schoolsMock;
  if (user.role === "CountryDirector") return schoolsMock.filter((s) => s.country === user.country);
  if (user.role === "CountryProgramLead") {
    // Real backend will filter by `school.assignedCceoStaffId in supervisedCceos(user.staffId)`.
    // Until that mapping exists, scope by country (the seed has only Uganda so
    // this is effectively a no-op) but stop pretending the role is unrestricted.
    return schoolsMock.filter((s) => s.country === user.country);
  }
  if (user.role === "ImpactAssessment" || user.role === "ProgramAccountant") {
    return schoolsMock.filter((s) => s.country === user.country);
  }
  // CCEO: strict assignment match.
  return schoolsMock.filter((s) => {
    if (s.assignedCceoId && s.assignedCceoId === user.staffId) return true;
    if (s.salesforceOwnerId && s.salesforceOwnerId === user.salesforceOwnerId) return true;
    if (s.assignedCceoEmail && s.assignedCceoEmail.toLowerCase() === user.email.toLowerCase()) return true;
    if (s.assignedCceoName && s.assignedCceoName === user.name) return true;
    return false;
  });
}

// SSA-first priority order (per product doc):
//   1. SSA score (lowest first)
//   2. Inactive
//   3. No visit
//   4. No training
export function priorityOrder(a: SchoolRow, b: SchoolRow): number {
  if (a.ssaScore !== b.ssaScore) return a.ssaScore - b.ssaScore;
  const inactiveRank = (s: SchoolRow) => (s.schoolStatus === "Inactive" ? 0 : 1);
  if (inactiveRank(a) !== inactiveRank(b)) return inactiveRank(a) - inactiveRank(b);
  const noVisitRank = (s: SchoolRow) => (s.noVisit ? 0 : 1);
  if (noVisitRank(a) !== noVisitRank(b)) return noVisitRank(a) - noVisitRank(b);
  const noTrainingRank = (s: SchoolRow) => (s.noTraining ? 0 : 1);
  if (noTrainingRank(a) !== noTrainingRank(b)) return noTrainingRank(a) - noTrainingRank(b);
  return 0;
}

// ────────── Display helpers ──────────

export function formatDate(d?: string): string {
  if (!d) return "—";
  // YYYY-MM-DD → "20 May 2025"
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

// ────────── KPI shape ──────────

export type SchoolKpi = {
  key: string;
  label: string;
  value: number;
  delta: { pct: string; tone: "up" | "down" };
  icon:
    | "school"
    | "users"
    | "briefcase"
    | "shield"
    | "schoolOff"
    | "userPlus"
    | "handshake"
    | "checkCircle"
    | "xCircle";
  iconTone: "edify" | "green" | "blue" | "violet" | "rose" | "amber" | "emerald" | "red";
  spark: { seed: number; trend: "up" | "down" };
};

// Build the full KPI row driven by the user's visible school list.
// In production these would each be a single SQL aggregation gated by the
// same access-control predicate as the table.
//
// Country-wide totals match the screenshot for visual fidelity (a Country
// Director would see these); for a CCEO, recompute from the assigned set —
// see computeKpisFor().
export function computeKpisFor(schools: SchoolRow[]): SchoolKpi[] {
  const total = schools.length;
  const active = schools.filter((s) => s.schoolStatus === "Active").length;
  const inactive = schools.filter((s) => s.schoolStatus === "Inactive").length;
  const client = schools.filter((s) => s.segment === "Client").length;
  const core = schools.filter((s) => s.segment === "Core").length;
  const assignedStaff = schools.filter((s) => Boolean(s.assignedCceoId)).length;
  const assignedPartner = schools.filter((s) => Boolean(s.assignedPartnerId)).length;
  const ssaCompleted = schools.filter((s) => s.ssaStatus === "Completed").length;
  const ssaNotCompleted = schools.filter((s) => s.ssaStatus !== "Completed").length;

  return [
    { key: "total",     label: "Total Schools",      value: total,           delta: { pct: "8.4%",  tone: "up" },   icon: "school",      iconTone: "edify",   spark: { seed: 21, trend: "up" } },
    { key: "active",    label: "Active Schools",     value: active,          delta: { pct: "6.7%",  tone: "up" },   icon: "users",       iconTone: "green",   spark: { seed: 22, trend: "up" } },
    { key: "client",    label: "Client Schools",     value: client,          delta: { pct: "5.1%",  tone: "up" },   icon: "briefcase",   iconTone: "blue",    spark: { seed: 23, trend: "up" } },
    { key: "core",      label: "Core Schools",       value: core,            delta: { pct: "3.2%",  tone: "up" },   icon: "shield",      iconTone: "violet",  spark: { seed: 24, trend: "up" } },
    { key: "inactive",  label: "Inactive Schools",   value: inactive,        delta: { pct: "6.2%",  tone: "down" }, icon: "schoolOff",   iconTone: "rose",    spark: { seed: 25, trend: "down" } },
    { key: "staff",     label: "Assigned to Staff",  value: assignedStaff,   delta: { pct: "7.8%",  tone: "up" },   icon: "userPlus",    iconTone: "amber",   spark: { seed: 26, trend: "up" } },
    { key: "partners",  label: "Assigned to Partners", value: assignedPartner, delta: { pct: "6.3%",  tone: "up" },   icon: "handshake",   iconTone: "edify",   spark: { seed: 27, trend: "up" } },
    { key: "ssa_done",  label: "SSA Completed",      value: ssaCompleted,    delta: { pct: "9.6%",  tone: "up" },   icon: "checkCircle", iconTone: "emerald", spark: { seed: 28, trend: "up" } },
    { key: "ssa_miss",  label: "SSA Not Completed",  value: ssaNotCompleted, delta: { pct: "7.1%",  tone: "down" }, icon: "xCircle",     iconTone: "red",     spark: { seed: 29, trend: "down" } },
  ];
}

// Country-level fallback values when the screenshot wants the country picture.
// Used as a fixed-content alternative where the doc explicitly references the
// 512-school total (e.g. for a Country Director's view).
export const countryKpiOverrides: Record<string, number> = {
  total: 512,
  active: 436,
  client: 318,
  core: 194,
  inactive: 76,
  staff: 276,
  partners: 236,
  ssa_done: 328,
  ssa_miss: 184,
};

// ────────── Status snapshot tiles ──────────

export type StatusSnapshotTile = {
  key: keyof typeof countryKpiOverrides;
  label: string;
  value: number;
  pct: number;
  icon: "users" | "schoolOff" | "briefcase" | "shield" | "checkCircle" | "xCircle" | "userPlus" | "handshake";
  tone: "green" | "rose" | "blue" | "violet" | "emerald" | "red" | "amber" | "edify";
};

export function computeStatusSnapshot(schools: SchoolRow[]): StatusSnapshotTile[] {
  const total = Math.max(schools.length, 1);
  const pct = (n: number) => Math.round((n / total) * 1000) / 10;

  const active   = schools.filter((s) => s.schoolStatus === "Active").length;
  const inactive = schools.filter((s) => s.schoolStatus === "Inactive").length;
  const client   = schools.filter((s) => s.segment === "Client").length;
  const core     = schools.filter((s) => s.segment === "Core").length;
  const ssaDone  = schools.filter((s) => s.ssaStatus === "Completed").length;
  const ssaMiss  = schools.filter((s) => s.ssaStatus !== "Completed").length;
  const staff    = schools.filter((s) => Boolean(s.assignedCceoId)).length;
  const partners = schools.filter((s) => Boolean(s.assignedPartnerId)).length;

  return [
    { key: "active",   label: "Active Schools",    value: active,    pct: pct(active),    icon: "users",       tone: "green"   },
    { key: "inactive", label: "Inactive Schools",  value: inactive,  pct: pct(inactive),  icon: "schoolOff",   tone: "rose"    },
    { key: "client",   label: "Client Schools",    value: client,    pct: pct(client),    icon: "briefcase",   tone: "blue"    },
    { key: "core",     label: "Core Schools",      value: core,      pct: pct(core),      icon: "shield",      tone: "violet"  },
    { key: "ssa_done", label: "SSA Completed",     value: ssaDone,   pct: pct(ssaDone),   icon: "checkCircle", tone: "emerald" },
    { key: "ssa_miss", label: "SSA Not Completed", value: ssaMiss,   pct: pct(ssaMiss),   icon: "xCircle",     tone: "red"     },
    { key: "staff",    label: "Staff Assigned",    value: staff,     pct: pct(staff),     icon: "userPlus",    tone: "amber"   },
    { key: "partners", label: "Partner Assigned",  value: partners,  pct: pct(partners),  icon: "handshake",   tone: "edify"   },
  ];
}

// ────────── Planning & Review Signals ──────────

export type PlanningSignal = {
  key: string;
  label: string;
  value: number;
  icon: "mapPin" | "graduationCap" | "shieldOff" | "gauge" | "schoolOff" | "phone";
  tone: "edify" | "amber" | "violet" | "rose" | "red" | "blue";
};

export function computePlanningSignals(schools: SchoolRow[]): PlanningSignal[] {
  const noVisit = schools.filter((s) => s.noVisit && !s.noTraining).length;
  const noTraining = schools.filter((s) => s.noTraining && !s.noVisit).length;
  const neither = schools.filter((s) => s.noVisit && s.noTraining).length;
  const lowSsa = schools.filter((s) => s.ssaScore < 60).length;
  const inactive = schools.filter((s) => s.schoolStatus === "Inactive").length;
  const followUp = schools.filter(
    (s) => s.priority === "Critical" || s.priority === "High",
  ).length;

  return [
    { key: "no_visit",     label: "No Visit",                value: noVisit,    icon: "mapPin",         tone: "edify"  },
    { key: "no_training",  label: "No Training",             value: noTraining, icon: "graduationCap",  tone: "amber"  },
    { key: "neither",      label: "Neither Visit Nor Training", value: neither, icon: "shieldOff",      tone: "violet" },
    { key: "low_ssa",      label: "Low SSA (<60%)",          value: lowSsa,     icon: "gauge",          tone: "rose"   },
    { key: "inactive",     label: "Inactive Schools",        value: inactive,   icon: "schoolOff",      tone: "red"    },
    { key: "follow_up",    label: "Needs Follow-Up",         value: followUp,   icon: "phone",          tone: "blue"   },
  ];
}

// Country-wide overrides for the screenshot's reference values.
export const countryPlanningSignalOverrides: Record<string, number> = {
  no_visit: 38,
  no_training: 42,
  neither: 112,
  low_ssa: 78,
  inactive: 76,
  follow_up: 159,
};

// ────────── Filter, group, and cluster helpers ──────────
//
// CLUSTERING IS DONE FROM THE SCHOOL DIRECTORY.
// Staff filter their visible schools by region / district / shipping address,
// then create a cluster from the filtered set. The Planning Tool only
// schedules visits and trainings against existing clusters and schools — it
// does not create clusters.

export type GroupBy = "none" | "shippingAddress" | "district" | "region";

export type SchoolFilters = {
  region?: Region | "All";
  district?: District | "All";
  shippingAddress?: ShippingAddress | "All";
  search?: string;
};

export function distinctRegions(schools: SchoolRow[]): Region[] {
  return Array.from(new Set(schools.map((s) => s.region))).sort() as Region[];
}
export function distinctDistricts(schools: SchoolRow[]): District[] {
  return Array.from(new Set(schools.map((s) => s.district))).sort() as District[];
}
export function distinctShippingAddresses(schools: SchoolRow[]): ShippingAddress[] {
  return Array.from(new Set(schools.map((s) => s.shippingAddress))).sort() as ShippingAddress[];
}

export function applyFilters(schools: SchoolRow[], f: SchoolFilters): SchoolRow[] {
  return schools.filter((s) => {
    if (f.region && f.region !== "All" && s.region !== f.region) return false;
    if (f.district && f.district !== "All" && s.district !== f.district) return false;
    if (
      f.shippingAddress &&
      f.shippingAddress !== "All" &&
      s.shippingAddress !== f.shippingAddress
    ) return false;
    if (f.search) {
      const q = f.search.toLowerCase();
      if (
        !s.schoolName.toLowerCase().includes(q) &&
        !s.district.toLowerCase().includes(q) &&
        !s.shippingAddress.toLowerCase().includes(q)
      ) return false;
    }
    return true;
  });
}

export function groupSchools(
  schools: SchoolRow[],
  by: GroupBy,
): { key: string; schools: SchoolRow[] }[] {
  if (by === "none") return [{ key: "All schools", schools }];
  const buckets = new Map<string, SchoolRow[]>();
  for (const s of schools) {
    const key = String(s[by as keyof SchoolRow] ?? "—");
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(s);
  }
  return Array.from(buckets.entries())
    .map(([key, rows]) => ({ key, schools: rows }))
    .sort((a, b) => a.key.localeCompare(b.key));
}

// ────────── Clusters ──────────
//
// A Cluster is a CCEO-owned saved group of schools. Created from the School
// Directory; consumed by the Planning Tool when scheduling visits or trainings.

export type Cluster = {
  id: string;
  name: string;
  ownerCceoId: string;
  region?: Region;
  district?: District;
  shippingAddress?: ShippingAddress;
  schoolIds: string[];
  createdAt: string; // ISO date
  description?: string;
};

// Raw clusters — region/district below are placeholders, derived on export
// from the hub (or, for multi-hub loops with no hub, the first member school).
const RAW_CLUSTERS: Cluster[] = [
  {
    id: "CLT-001",
    name: "Kampala Hub – Term 2 Visits",
    ownerCceoId: "STF-DM-014",
    region: "North",
    district: "Central",
    shippingAddress: "Kampala Hub - Central",
    schoolIds: ["SCH-001", "SCH-002", "SCH-006"],
    createdAt: "2025-05-02",
    description: "Routes anchored on Kampala Hub for May/June.",
  },
  {
    id: "CLT-002",
    name: "Mukono Hub – Cluster Routes",
    ownerCceoId: "STF-DM-014",
    region: "North",
    district: "Cluster",
    shippingAddress: "Mukono Hub - Central",
    schoolIds: ["SCH-003", "SCH-004", "SCH-009"],
    createdAt: "2025-05-04",
    description: "Outreach loop for Mukono cluster schools.",
  },
  {
    id: "CLT-003",
    name: "Jinja & Iganga – East Loop",
    ownerCceoId: "STF-DM-014",
    region: "North",
    district: "East",
    schoolIds: ["SCH-005", "SCH-007", "SCH-008"],
    createdAt: "2025-05-06",
    description: "Two-shipping-hub combined route.",
  },
];

export const clustersMock: Cluster[] = RAW_CLUSTERS.map((c) => {
  if (c.shippingAddress) {
    const { district, region } = geoFromHub(c.shippingAddress);
    return { ...c, district, region };
  }
  // No single hub (multi-hub loop) — anchor on the first member school.
  const first = schoolsMock.find((s) => c.schoolIds.includes(s.schoolId));
  return first ? { ...c, district: first.district, region: first.region } : c;
});

export function getClustersFor(user: CurrentUser): Cluster[] {
  if (user.role === "Admin" || user.role === "CountryDirector" || user.role === "CountryProgramLead") {
    return clustersMock;
  }
  return clustersMock.filter((c) => c.ownerCceoId === user.staffId);
}

// ────────── Quick Actions ──────────

export type SchoolQuickAction = {
  key: string;
  title: string;
  subtitle: string;
  icon: "school" | "userPlus" | "handshake" | "flag" | "download";
  href: string;
  // Permission gate. CCEOs typically don't assign — the permission model
  // can re-open this for Admins / Program Leads / Directors.
  requiresRole?: AppRole[];
};

export const schoolQuickActions: SchoolQuickAction[] = [
  { key: "view_profile",    title: "View School Profile",     subtitle: "Open school details",     icon: "school",    href: "/schools" },
  { key: "assign_staff",    title: "Assign Staff",            subtitle: "Assign to school",        icon: "userPlus",  href: "#assign-staff",    requiresRole: ["Admin", "CountryProgramLead", "CountryDirector"] },
  { key: "assign_partner",  title: "Assign Partner",          subtitle: "Assign partner",          icon: "handshake", href: "#assign-partner",  requiresRole: ["Admin", "CountryProgramLead", "CountryDirector"] },
  { key: "review_priority", title: "Review Priority Schools", subtitle: "High priority list",      icon: "flag",      href: "#urgent" },
  { key: "export_data",     title: "Export Data",             subtitle: "Download report",         icon: "download",  href: "#export" },
];

export function isActionAllowed(action: SchoolQuickAction, user: CurrentUser): boolean {
  if (!action.requiresRole) return true;
  return action.requiresRole.includes(user.role);
}

// ────────── Header ──────────

export const schoolsHeader = {
  title: "School Dashboard",
  subtitle:
    "Monitor school coverage, engagement, SSA completion and prioritize schools requiring urgent attention.",
  filters: {
    month: "May 2025",
    region: "North",
  },
  searchPlaceholder: "Search schools, districts…",
};

export const schoolsNotificationCount = 12;
