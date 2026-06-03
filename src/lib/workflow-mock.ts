// Workflow data layer for Edify Planning Tool + Role Dashboards.
// Status names and rules trace back to the product document and map onto the
// existing Prisma schema. UI consumes these arrays today; backend can swap them
// for `db.*` calls without changing any dashboard code.

// ────────── Canonical status enums (from the product document) ──────────

export const PLAN_STATUSES = [
  "Recommended",
  "Scheduled",
  "Submitted for Approval",
  "Approved",
  "Returned",
  "Funded/Ready",
  "Active Todo",
  "Awaiting Salesforce ID",
  "Submitted for Verification",
  "Verified",
  "Closed",
] as const;
export type PlanStatus = (typeof PLAN_STATUSES)[number];

export const DATA_QUALITY_STATUSES = [
  "Ready for Planning",
  "Needs Location Update",
  "Needs Contact Update",
  "Needs Type Mapping",
  "Needs CCEO Assignment",
  "Needs Coordinates",
  "Inactive",
] as const;
export type DataQualityStatus = (typeof DATA_QUALITY_STATUSES)[number];

export const ROUTE_QUALITIES = ["Good", "Heavy but Possible", "Poor Route", "Needs Review"] as const;
export type RouteQuality = (typeof ROUTE_QUALITIES)[number];

export const CONFLICT_SEVERITIES = ["Low", "Medium", "High", "Critical"] as const;
export type ConflictSeverity = (typeof CONFLICT_SEVERITIES)[number];

export const SF_MATCH_STATES = ["Strong match", "Multiple matches", "No match", "Orphan Salesforce Activity"] as const;
export type SfMatchState = (typeof SF_MATCH_STATES)[number];

export type Role =
  | "CCEO"
  | "CountryProgramLead"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "CountryDirector"
  | "RVP";

// ────────── Roles registry (used by sidebar, role switcher, dashboards) ──────────

export type RoleProfile = {
  id: Role;
  name: string;
  initials: string;
  title: string;
  scope: string;
  online: boolean;
  homePath: string;
  brandSubtitle: string;
};

export const roleProfiles: Record<Role, RoleProfile> = {
  CCEO: {
    id: "CCEO",
    name: "Sarah Okello",
    initials: "SO",
    title: "Cluster Chief Education Officer",
    scope: "Kigun District",
    online: true,
    homePath: "/",
    brandSubtitle: "Field Planning Workspace",
  },
  CountryProgramLead: {
    id: "CountryProgramLead",
    name: "Joseph Kato",
    initials: "JK",
    title: "Country Program Lead",
    scope: "Uganda Program",
    online: true,
    homePath: "/dashboards/cpl",
    brandSubtitle: "Program Oversight Console",
  },
  ProgramAccountant: {
    id: "ProgramAccountant",
    name: "Mary Asiimwe",
    initials: "MA",
    title: "Program Accountant",
    scope: "Uganda Finance",
    online: true,
    homePath: "/dashboards/accountant",
    brandSubtitle: "Program Finance Console",
  },
  ImpactAssessment: {
    id: "ImpactAssessment",
    name: "Robert Otim",
    initials: "RO",
    title: "M&E / Impact Assessment",
    scope: "Uganda Verification",
    online: true,
    homePath: "/dashboards/impact",
    brandSubtitle: "Verification & Impact Console",
  },
  CountryDirector: {
    id: "CountryDirector",
    name: "Grace Nankunda",
    initials: "GN",
    title: "Country Director",
    scope: "Edify Uganda",
    online: true,
    homePath: "/dashboards/director",
    brandSubtitle: "Country Leadership Console",
  },
  RVP: {
    id: "RVP",
    name: "Daniel Mwangi",
    initials: "DM",
    title: "Regional Vice President",
    scope: "East Africa Region",
    online: true,
    homePath: "/dashboards/rvp",
    brandSubtitle: "Regional Leadership Console",
  },
};

// ────────── Conflicts (planning-time + supervisor visibility) ──────────

export type Conflict = {
  id: string;
  severity: ConflictSeverity;
  kind:
    | "Missing cluster date"
    | "Missing month/week"
    | "Leave conflict"
    | "Public holiday conflict"
    | "Staff conference week conflict"
    | "Capacity overload"
    | "Under-planning"
    | "Partner capacity full"
    | "Non-certified partner"
    | "Duplicate cluster assignment"
    | "Target shortfall risk"
    | "Salesforce backlog risk"
    | "Missing coordinates"
    | "Poor route quality"
    | "Excessive travel time"
    | "Cross-district overload"
    | "Staff far from assigned schools"
    | "Route not reviewed";
  message: string;
  affects: string;
  staff?: string;
};

export const conflicts: Conflict[] = [
  { id: "c1", severity: "Critical", kind: "Salesforce backlog risk",   message: "11 activities awaiting Salesforce ID > 5 days",            affects: "Kigun Central + Maryhill clusters", staff: "Sarah Okello" },
  { id: "c2", severity: "High",     kind: "Capacity overload",          message: "Week 2 plans 28 activities — recommended cap is 22",        affects: "Kigun West Cluster",               staff: "Sarah Okello" },
  { id: "c3", severity: "High",     kind: "Non-certified partner",      message: "Partner 'Hope Africa' is not certified for SSA visits",     affects: "Olive Children's School",          staff: "Sarah Okello" },
  { id: "c4", severity: "Medium",   kind: "Public holiday conflict",    message: "May 13 (Eid al-Fitr) overlaps planned cluster training",   affects: "Maryhill Cluster",                 staff: "Joseph Kato" },
  { id: "c5", severity: "Medium",   kind: "Poor route quality",         message: "Day 14 route has >180 min travel — review or reorder",     affects: "North Ridge Cluster",              staff: "Sarah Okello" },
  { id: "c6", severity: "Medium",   kind: "Missing cluster date",       message: "Eastside Cluster Meeting has no exact date set",            affects: "Eastside Cluster",                 staff: "Sarah Okello" },
  { id: "c7", severity: "Low",      kind: "Under-planning",             message: "Week 5 has only 10 in-school activities planned",           affects: "Kigun District",                   staff: "Sarah Okello" },
  { id: "c8", severity: "High",     kind: "Target shortfall risk",      message: "Verified visits forecast at 88% of monthly target",        affects: "Uganda program",                   staff: "Country Program Lead" },
];

// ────────── Plan approvals (Country Program Lead queue) ──────────

export type PlanApproval = {
  id: string;
  staff: string;
  scope: string;
  activities: number;
  exceptions: number;
  submittedOn: string;
  status: Extract<PlanStatus, "Submitted for Approval" | "Approved" | "Returned">;
};

export const planApprovals: PlanApproval[] = [
  { id: "pa1", staff: "Sarah Okello",   scope: "Kigun District · May 2025",      activities: 132, exceptions: 3, submittedOn: "May 02", status: "Submitted for Approval" },
  { id: "pa2", staff: "Brian Lumumba",  scope: "Mbarara District · May 2025",    activities: 118, exceptions: 1, submittedOn: "May 02", status: "Submitted for Approval" },
  { id: "pa3", staff: "Naome Kintu",    scope: "Kampala District · May 2025",    activities: 144, exceptions: 5, submittedOn: "May 03", status: "Submitted for Approval" },
  { id: "pa4", staff: "Peter Ssempa",   scope: "Wakiso District · May 2025",     activities: 121, exceptions: 0, submittedOn: "Apr 30", status: "Returned" },
  { id: "pa5", staff: "Esther Aheebwa", scope: "Mukono District · May 2025",     activities: 137, exceptions: 2, submittedOn: "Apr 29", status: "Approved" },
];

// ────────── Fund requests (Accountant + Country Director path) ──────────

export type FundCostItem =
  | "Staff school visit"
  | "Partner school visit"
  | "Participant meals"
  | "Partner training fee"
  | "Staff in-school coaching"
  | "Partner in-school training"
  | "SSA support"
  | "MSC collection"
  | "Exam result collection"
  | "Group training";

export type FundRequest = {
  id: string;
  district: string;
  staff: string;
  month: string;
  lineItems: { item: FundCostItem; qty: number; rate: number }[];
  status: "Pending Accountant" | "Pending Director" | "Pending RVP" | "Disbursed";
  submittedOn: string;
};

export const fundRequests: FundRequest[] = [
  {
    id: "fr1",
    district: "Kigun District",
    staff: "Sarah Okello",
    month: "May 2025",
    lineItems: [
      { item: "Staff school visit",         qty: 64, rate: 12000 },
      { item: "Partner school visit",       qty: 82, rate: 18000 },
      { item: "Participant meals",          qty: 14, rate: 75000 },
      { item: "Partner training fee",       qty: 14, rate: 250000 },
      { item: "Staff in-school coaching",   qty: 32, rate: 15000 },
      { item: "MSC collection",             qty: 6,  rate: 9000 },
    ],
    status: "Pending Director",
    submittedOn: "May 03",
  },
  {
    id: "fr2",
    district: "Mbarara District",
    staff: "Brian Lumumba",
    month: "May 2025",
    lineItems: [
      { item: "Staff school visit",         qty: 58, rate: 12000 },
      { item: "Partner school visit",       qty: 64, rate: 18000 },
      { item: "Participant meals",          qty: 11, rate: 75000 },
      { item: "Partner training fee",       qty: 11, rate: 250000 },
      { item: "SSA support",                qty: 9,  rate: 8000 },
    ],
    status: "Pending Accountant",
    submittedOn: "May 03",
  },
  {
    id: "fr3",
    district: "Kampala District",
    staff: "Naome Kintu",
    month: "May 2025",
    lineItems: [
      { item: "Staff school visit",         qty: 71, rate: 14000 },
      { item: "Partner school visit",       qty: 88, rate: 20000 },
      { item: "Participant meals",          qty: 16, rate: 80000 },
      { item: "Partner training fee",       qty: 16, rate: 280000 },
      { item: "Group training",             qty: 4,  rate: 350000 },
      { item: "Exam result collection",     qty: 7,  rate: 9000 },
    ],
    status: "Pending Accountant",
    submittedOn: "May 03",
  },
  {
    id: "fr4",
    district: "Mukono District",
    staff: "Esther Aheebwa",
    month: "Apr 2025",
    lineItems: [
      { item: "Staff school visit",         qty: 60, rate: 12000 },
      { item: "Partner school visit",       qty: 70, rate: 18000 },
      { item: "Participant meals",          qty: 12, rate: 75000 },
    ],
    status: "Disbursed",
    submittedOn: "Apr 28",
  },
];

export function fundRequestTotal(fr: FundRequest) {
  return fr.lineItems.reduce((acc, li) => acc + li.qty * li.rate, 0);
}

// Fund-request approval chain. `approve` advances one stage, `return` steps
// back one stage, `disburse` finalises from the last approval stage. Returns
// the mutated request, or undefined when the action is invalid for the
// current status (callers surface this as WRONG_STATUS).
const FUND_REQUEST_CHAIN: FundRequest["status"][] = [
  "Pending Accountant",
  "Pending Director",
  "Pending RVP",
  "Disbursed",
];

export function transitionFundRequest(
  id: string,
  action: "approve" | "return" | "disburse",
  _note?: string,
): FundRequest | undefined {
  const fr = fundRequests.find((f) => f.id === id);
  if (!fr) return undefined;
  const i = FUND_REQUEST_CHAIN.indexOf(fr.status);

  if (action === "disburse") {
    if (fr.status !== "Pending RVP") return undefined;
    fr.status = "Disbursed";
    return fr;
  }
  if (action === "approve") {
    if (i < 0 || i >= FUND_REQUEST_CHAIN.length - 1) return undefined;
    fr.status = FUND_REQUEST_CHAIN[i + 1];
    return fr;
  }
  // "return" — step back one approval stage (not valid once disbursed).
  if (i <= 0 || fr.status === "Disbursed") return undefined;
  fr.status = FUND_REQUEST_CHAIN[i - 1];
  return fr;
}

// ────────── Salesforce match queue (CCEO + Impact Assessment) ──────────

export type SalesforceMatchRow = {
  id: string;
  activity: string;
  school: string;
  staff: string;
  plannedWindow: string;
  matchState: SfMatchState;
  sfId?: string;
  daysOpen: number;
};

export const salesforceMatches: SalesforceMatchRow[] = [
  { id: "sm1", activity: "In-School Coaching", school: "Hope Primary School",  staff: "Sarah Okello",  plannedWindow: "May / Wk 1",       matchState: "Strong match",      sfId: "SFA-002841", daysOpen: 1 },
  { id: "sm2", activity: "School Visit",       school: "St. Peter Primary",    staff: "Sarah Okello",  plannedWindow: "May / Wk 1",       matchState: "Strong match",      sfId: "SFA-002844", daysOpen: 2 },
  { id: "sm3", activity: "SSA Follow-up",      school: "Grace Primary School", staff: "Sarah Okello",  plannedWindow: "May / Wk 1",       matchState: "Multiple matches",                       daysOpen: 3 },
  { id: "sm4", activity: "Cluster Training",   school: "Kigun Central Cluster",staff: "Sarah Okello",  plannedWindow: "May 06",           matchState: "No match",                              daysOpen: 5 },
  { id: "sm5", activity: "Handover Meeting",   school: "Bright Future PS",     staff: "Brian Lumumba", plannedWindow: "May / Wk 1",       matchState: "Strong match",      sfId: "SFA-002850", daysOpen: 1 },
  { id: "sm6", activity: "Partner Visit",      school: "—",                    staff: "—",             plannedWindow: "—",                matchState: "Orphan Salesforce Activity", sfId: "SFA-002901", daysOpen: 0 },
];

// ────────── Verification queue (Impact Assessment) ──────────

export type VerificationRow = {
  id: string;
  activity: string;
  school: string;
  staff: string;
  sfId: string;
  evidence: "Complete" | "Missing photo" | "Missing signoff" | "Unverifiable";
  validVisit: "Yes" | "No" | "N/A";
  status: Extract<PlanStatus, "Submitted for Verification" | "Verified" | "Returned">;
  reason?: string;
};

export const verificationQueue: VerificationRow[] = [
  { id: "v1", activity: "In-School Coaching",     school: "Hope Primary School",     staff: "Sarah Okello",   sfId: "SFA-002841", evidence: "Complete",         validVisit: "Yes", status: "Submitted for Verification" },
  { id: "v2", activity: "School Visit",           school: "St. Peter Primary",       staff: "Sarah Okello",   sfId: "SFA-002844", evidence: "Missing photo",    validVisit: "Yes", status: "Submitted for Verification", reason: "No school sign-in photo" },
  { id: "v3", activity: "SSA Follow-up",          school: "Grace Primary School",    staff: "Sarah Okello",   sfId: "SFA-002851", evidence: "Complete",         validVisit: "No",  status: "Submitted for Verification", reason: "SSA support visits do not count as valid visits" },
  { id: "v4", activity: "Partner Visit",          school: "Olive Children's School", staff: "Hope Africa",    sfId: "SFA-002857", evidence: "Complete",         validVisit: "No",  status: "Returned",                  reason: "Non-certified partner" },
  { id: "v5", activity: "Cluster Training",       school: "Maryhill Cluster",        staff: "Brian Lumumba",  sfId: "SFA-002860", evidence: "Complete",         validVisit: "Yes", status: "Verified" },
  { id: "v6", activity: "In-School Training",     school: "Riverside Primary",       staff: "Naome Kintu",    sfId: "SFA-002862", evidence: "Missing signoff",  validVisit: "Yes", status: "Submitted for Verification", reason: "Headteacher signoff missing" },
];

// ────────── Valid visit rules (used in Impact dashboard + tooltips) ──────────

export type ValidVisitRule = {
  kind: string;
  counts: boolean;
  reason: string;
};

export const validVisitRules: ValidVisitRule[] = [
  { kind: "Staff visit",                   counts: true,  reason: "Direct CCEO field engagement counts" },
  { kind: "Certified partner visit",       counts: true,  reason: "Certified partners qualify as a valid visit" },
  { kind: "Non-certified partner visit",   counts: false, reason: "Partner must be certified before counting" },
  { kind: "Training visit",                counts: true,  reason: "Cluster or in-school training counts" },
  { kind: "SSA support visit",             counts: false, reason: "SSA support is not a programmatic visit" },
  { kind: "In-school coaching/training",   counts: true,  reason: "Direct delivery of intervention counts" },
];

// ────────── Route suggestions (CCEO + supervisor) ──────────

export type RouteSuggestion = {
  id: string;
  name: string;
  staff: string;
  schools: number;
  travelMins: number;
  quality: RouteQuality;
  note: string;
};

export const routeSuggestions: RouteSuggestion[] = [
  { id: "r1", name: "Kigun West Loop",    staff: "Sarah Okello",  schools: 4, travelMins: 95,  quality: "Good",                note: "These 4 schools are close — visiting together saves travel time." },
  { id: "r2", name: "Maryhill Bundle",    staff: "Sarah Okello",  schools: 6, travelMins: 145, quality: "Heavy but Possible",  note: "Doable in one day, but plan an early start." },
  { id: "r3", name: "North Ridge Sweep",  staff: "Sarah Okello",  schools: 5, travelMins: 220, quality: "Poor Route",          note: "Travel exceeds 3 hrs — consider splitting across two days." },
  { id: "r4", name: "Eastside Quick Run", staff: "Sarah Okello",  schools: 3, travelMins: 60,  quality: "Good",                note: "Tight cluster — easy half-day run." },
  { id: "r5", name: "Kampala Crosstown",  staff: "Naome Kintu",   schools: 5, travelMins: 175, quality: "Needs Review",        note: "Two schools missing coordinates — confirm before routing." },
];

// ────────── Returned corrections (CCEO action queue) ──────────

export type ReturnedCorrection = {
  id: string;
  activity: string;
  school: string;
  reason: string;
  returnedOn: string;
  ageDays: number;
};

export const returnedCorrections: ReturnedCorrection[] = [
  { id: "rc1", activity: "School Visit",       school: "St. Peter Primary",    reason: "Missing school sign-in photo",     returnedOn: "May 04", ageDays: 4 },
  { id: "rc2", activity: "In-School Training", school: "Riverside Primary",    reason: "Headteacher signoff missing",      returnedOn: "May 03", ageDays: 5 },
  { id: "rc3", activity: "SSA Follow-up",      school: "Grace Primary School", reason: "Wrong intervention selected",      returnedOn: "May 02", ageDays: 6 },
];

// ────────── Special projects (outside SSA 8) ──────────

export type SpecialProjectKey =
  | "EdTech"
  | "CCSEL"
  | "IDCCE"
  | "ECC"
  | "UCU";

export type SpecialProject = {
  key: SpecialProjectKey;
  name: string;
  fullName: string;
  cohort: string;
  enrolled: number;
  completed: number;
  progressPct: number;
  staffOnProject: number;
  partnerOnProject: number;
  teachersImpacted?: number;
  schoolsImpacted: number;
  excludedFromSsaRecs: true;
  funder?: string;
  status: "Active" | "Onboarding" | "Wrap-up";
};

export const specialProjects: SpecialProject[] = [
  {
    key: "EdTech", name: "Education Technology", fullName: "Education Technology",
    cohort: "Cohort 2 · 2024–2025", enrolled: 84, completed: 52, progressPct: 62,
    staffOnProject: 6, partnerOnProject: 4, teachersImpacted: 312, schoolsImpacted: 38,
    excludedFromSsaRecs: true, funder: "Mastercard Foundation", status: "Active",
  },
  {
    key: "CCSEL", name: "CCSEL", fullName: "Christ-Centered Social Emotional Learning",
    cohort: "Cohort 1 · 2025", enrolled: 120, completed: 28, progressPct: 23,
    staffOnProject: 4, partnerOnProject: 6, teachersImpacted: 480, schoolsImpacted: 60,
    excludedFromSsaRecs: true, funder: "Edify Reserve", status: "Active",
  },
  {
    key: "IDCCE", name: "IDCCE", fullName: "International Diploma in Christ-Centered Education",
    cohort: "Cohort 3 · 2024–2026", enrolled: 64, completed: 18, progressPct: 28,
    staffOnProject: 2, partnerOnProject: 3, teachersImpacted: 64, schoolsImpacted: 64,
    excludedFromSsaRecs: true, funder: "Tearfund", status: "Active",
  },
  {
    key: "ECC", name: "ECC", fullName: "Early Childhood Curriculum",
    cohort: "Cohort 1 · 2025", enrolled: 42, completed: 6, progressPct: 14,
    staffOnProject: 3, partnerOnProject: 2, teachersImpacted: 168, schoolsImpacted: 42,
    excludedFromSsaRecs: true, funder: "Stronger Foundations", status: "Onboarding",
  },
  {
    key: "UCU", name: "UCU TUP", fullName: "UCU Teacher Upgrading Program",
    cohort: "Cohort 4 · 2024–2025", enrolled: 36, completed: 32, progressPct: 89,
    staffOnProject: 1, partnerOnProject: 1, teachersImpacted: 36, schoolsImpacted: 22,
    excludedFromSsaRecs: true, funder: "UCU Partnership", status: "Wrap-up",
  },
];

// ────────── Schools dashboard data ──────────

export type SchoolStatus = "Active" | "Inactive" | "Becoming Inactive";
export type SchoolSegment = "Client" | "Core";

export type SchoolRow = {
  id: string;
  name: string;
  cluster: string;
  district: string;
  ssaScore: number; // %
  status: SchoolStatus;
  segment: SchoolSegment;
  ssaCompleted: boolean;
  weakestIntervention: string;
  recommended: string;
  cceo: string;
  partner: string;
  lastVisit: string;
  noTraining: boolean;
  noVisit: boolean;
  dataQuality: DataQualityStatus;
};

export const schoolsCatalog: SchoolRow[] = [
  { id: "sch-1",  name: "Hope Primary School",       cluster: "Kigun Central Cluster", district: "Kigun",   ssaScore: 19, status: "Becoming Inactive", segment: "Client", ssaCompleted: true,  weakestIntervention: "Attendance",          recommended: "SSA Support + Home Visits",     cceo: "Sarah Okello", partner: "Eagle Africa",      lastVisit: "May 02", noTraining: true,  noVisit: true,  dataQuality: "Ready for Planning" },
  { id: "sch-2",  name: "Greenfields Primary School",cluster: "Kigun Central Cluster", district: "Kigun",   ssaScore: 42, status: "Active",            segment: "Client", ssaCompleted: true,  weakestIntervention: "Teaching Learning",   recommended: "In-School Coaching",            cceo: "Sarah Okello", partner: "Hope Africa",       lastVisit: "May 02", noTraining: true,  noVisit: false, dataQuality: "Ready for Planning" },
  { id: "sch-3",  name: "Maple Grove Primary School",cluster: "Maryhill Cluster",      district: "Kigun",   ssaScore: 48, status: "Active",            segment: "Client", ssaCompleted: true,  weakestIntervention: "Teaching Learning",   recommended: "In-School Coaching",            cceo: "Sarah Okello", partner: "Hope Africa",       lastVisit: "Apr 28", noTraining: true,  noVisit: true,  dataQuality: "Ready for Planning" },
  { id: "sch-4",  name: "Sunrayvale Primary School", cluster: "Sunrayvale Cluster",    district: "Mbarara", ssaScore: 58, status: "Active",            segment: "Core",   ssaCompleted: true,  weakestIntervention: "Foundational Literacy", recommended: "Cluster Training",            cceo: "Brian Lumumba",partner: "Bright Path",       lastVisit: "Apr 30", noTraining: false, noVisit: true,  dataQuality: "Ready for Planning" },
  { id: "sch-5",  name: "Riverside Primary School",  cluster: "Kigun West Cluster",    district: "Kigun",   ssaScore: 31, status: "Becoming Inactive", segment: "Client", ssaCompleted: true,  weakestIntervention: "Numeracy",            recommended: "In-School Coaching + Visit",    cceo: "Sarah Okello", partner: "Eagle Africa",      lastVisit: "Apr 18", noTraining: true,  noVisit: true,  dataQuality: "Ready for Planning" },
  { id: "sch-6",  name: "St. Peter Primary",         cluster: "Maryhill Cluster",      district: "Kigun",   ssaScore: 38, status: "Active",            segment: "Client", ssaCompleted: false, weakestIntervention: "Numeracy",            recommended: "Complete SSA",                  cceo: "Sarah Okello", partner: "Hope Africa",       lastVisit: "—",       noTraining: true,  noVisit: true,  dataQuality: "Needs Coordinates" },
  { id: "sch-7",  name: "Olive Children's School",   cluster: "Kigun East Cluster",    district: "Kigun",   ssaScore: 48, status: "Active",            segment: "Core",   ssaCompleted: true,  weakestIntervention: "Classroom Practice",  recommended: "Partner Coaching",              cceo: "Sarah Okello", partner: "Hope Africa",       lastVisit: "Apr 18", noTraining: false, noVisit: false, dataQuality: "Ready for Planning" },
  { id: "sch-8",  name: "Bright Future PS",          cluster: "Maryhill Cluster",      district: "Kigun",   ssaScore: 25, status: "Becoming Inactive", segment: "Client", ssaCompleted: true,  weakestIntervention: "Attendance",          recommended: "SSA Support + Home Visits",     cceo: "Brian Lumumba",partner: "Bright Path",       lastVisit: "—",       noTraining: true,  noVisit: true,  dataQuality: "Ready for Planning" },
  { id: "sch-9",  name: "Westview Primary",          cluster: "Westview Cluster",      district: "Wakiso",  ssaScore: 67, status: "Active",            segment: "Core",   ssaCompleted: true,  weakestIntervention: "Classroom Practice",  recommended: "Cluster Training",              cceo: "Peter Ssempa", partner: "Lumiere",           lastVisit: "May 01", noTraining: false, noVisit: false, dataQuality: "Ready for Planning" },
  { id: "sch-10", name: "Hilltop Primary School",    cluster: "Kampala North Cluster", district: "Kampala", ssaScore: 19, status: "Becoming Inactive", segment: "Client", ssaCompleted: false, weakestIntervention: "Attendance",          recommended: "Complete SSA + Home Visits",    cceo: "Naome Kintu",  partner: "Hope Africa",       lastVisit: "—",       noTraining: true,  noVisit: true,  dataQuality: "Needs Contact Update" },
  { id: "sch-11", name: "Mukono Hill Primary",       cluster: "Mukono East Cluster",   district: "Mukono",  ssaScore: 71, status: "Active",            segment: "Core",   ssaCompleted: true,  weakestIntervention: "Numeracy",            recommended: "In-School Coaching",            cceo: "Esther Aheebwa", partner: "Lumiere",         lastVisit: "Apr 26", noTraining: false, noVisit: false, dataQuality: "Ready for Planning" },
  { id: "sch-12", name: "Lake Shore Primary",        cluster: "Mbarara West Cluster",  district: "Mbarara", ssaScore: 34, status: "Active",            segment: "Client", ssaCompleted: true,  weakestIntervention: "Foundational Literacy", recommended: "In-School Coaching",          cceo: "Brian Lumumba",partner: "Bright Path",       lastVisit: "Apr 22", noTraining: true,  noVisit: false, dataQuality: "Ready for Planning" },
];

// ────────── Country / region rollups ──────────

export type DistrictRollup = {
  district: string;
  cceo: string;
  schools: number;
  active: number;
  inactive: number;
  ssaCompletedPct: number;
  verifiedPct: number;
  validVisitPct: number;
  monthlyTargetPct: number;
};

export const districtRollups: DistrictRollup[] = [
  { district: "Kigun",    cceo: "Sarah Okello",   schools: 42, active: 34, inactive: 8,  ssaCompletedPct: 78, verifiedPct: 92, validVisitPct: 88, monthlyTargetPct: 81 },
  { district: "Mbarara",  cceo: "Brian Lumumba",  schools: 38, active: 31, inactive: 7,  ssaCompletedPct: 71, verifiedPct: 88, validVisitPct: 84, monthlyTargetPct: 76 },
  { district: "Kampala",  cceo: "Naome Kintu",    schools: 47, active: 38, inactive: 9,  ssaCompletedPct: 64, verifiedPct: 81, validVisitPct: 79, monthlyTargetPct: 70 },
  { district: "Wakiso",   cceo: "Peter Ssempa",   schools: 33, active: 28, inactive: 5,  ssaCompletedPct: 82, verifiedPct: 94, validVisitPct: 90, monthlyTargetPct: 85 },
  { district: "Mukono",   cceo: "Esther Aheebwa", schools: 31, active: 26, inactive: 5,  ssaCompletedPct: 80, verifiedPct: 91, validVisitPct: 88, monthlyTargetPct: 83 },
];

export type CountryRollup = {
  country: string;
  director: string;
  schools: number;
  monthlyTargetPct: number;
  validVisitPct: number;
  ssaCompletedPct: number;
  fundsCommittedUgxM: number;
  fundsDisbursedUgxM: number;
  specialProjects: number;
};

export const countryRollups: CountryRollup[] = [
  { country: "Uganda",  director: "Grace Nankunda",  schools: 191, monthlyTargetPct: 79, validVisitPct: 86, ssaCompletedPct: 75, fundsCommittedUgxM: 824, fundsDisbursedUgxM: 612, specialProjects: 5 },
  { country: "Kenya",   director: "Mercy Wairimu",   schools: 142, monthlyTargetPct: 73, validVisitPct: 81, ssaCompletedPct: 68, fundsCommittedUgxM: 690, fundsDisbursedUgxM: 521, specialProjects: 4 },
  { country: "Rwanda",  director: "Eric Habimana",   schools: 88,  monthlyTargetPct: 84, validVisitPct: 89, ssaCompletedPct: 82, fundsCommittedUgxM: 410, fundsDisbursedUgxM: 318, specialProjects: 3 },
  { country: "Tanzania",director: "Asha Mwakalyelye",schools: 124, monthlyTargetPct: 70, validVisitPct: 78, ssaCompletedPct: 64, fundsCommittedUgxM: 595, fundsDisbursedUgxM: 401, specialProjects: 3 },
];

// ────────── Cost settings (used by Accountant + Director) ──────────

export const costSettings: { item: FundCostItem; defaultRate: number; unit: string }[] = [
  { item: "Staff school visit",         defaultRate: 12000,  unit: "per visit" },
  { item: "Partner school visit",       defaultRate: 18000,  unit: "per visit" },
  { item: "Participant meals",          defaultRate: 75000,  unit: "per session" },
  { item: "Partner training fee",       defaultRate: 250000, unit: "per training" },
  { item: "Staff in-school coaching",   defaultRate: 15000,  unit: "per session" },
  { item: "Partner in-school training", defaultRate: 22000,  unit: "per session" },
  { item: "SSA support",                defaultRate: 8000,   unit: "per support" },
  { item: "MSC collection",             defaultRate: 9000,   unit: "per record" },
  { item: "Exam result collection",     defaultRate: 9000,   unit: "per record" },
  { item: "Group training",             defaultRate: 350000, unit: "per cohort" },
];

// ────────── Helpers ──────────

export const formatUgx = (n: number) =>
  new Intl.NumberFormat("en-UG", { style: "currency", currency: "UGX", maximumFractionDigits: 0 }).format(n);

export const conflictTone = (s: ConflictSeverity) =>
  s === "Critical" ? "red" : s === "High" ? "amber" : s === "Medium" ? "amber" : "grey";

export const matchTone = (s: SfMatchState) =>
  s === "Strong match" ? "green" : s === "Multiple matches" ? "amber" : s === "No match" ? "red" : "amber";

export const routeTone = (q: RouteQuality) =>
  q === "Good" ? "green" : q === "Heavy but Possible" ? "amber" : q === "Poor Route" ? "red" : "amber";

export const planStatusTone = (s: PlanStatus) =>
  s === "Verified" || s === "Closed" || s === "Approved"
    ? "green"
    : s === "Returned"
      ? "red"
      : s === "Submitted for Approval" || s === "Submitted for Verification" || s === "Awaiting Salesforce ID"
        ? "amber"
        : "blue";
