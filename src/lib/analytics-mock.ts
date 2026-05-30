// Field Performance & School Improvement Analytics — mock data.
//
// This is the evidence centre of the planning tool. The data deliberately
// separates SIX states of work so analytics never rewards activity alone:
//
//   Planned → Completed → Salesforce Submitted → IA Verified
//           → School Improved → Learner Improved
//
// Every section below feeds one tab of the analytics page.

export const analyticsMeta = {
  periodLabel: "May 2025",
  fyLabel: "FY 2024/25",
  country: "Uganda",
};

// ────────── Insight Hero ───────────────────────────────────────────────

export const insightHero = {
  headline:
    "This Month CCEOs completed 79% of planned activities, but only 66% have been verified by Impact Assessment. Schools receiving verified coaching improved SSA by +0.6, and One Test literacy rose +9pp in assessed schools.",
  chips: [
    { label: "79% completed",        tone: "emerald" as const },
    { label: "66% verified",         tone: "sky" as const },
    { label: "+0.6 SSA growth",      tone: "emerald" as const },
    { label: "+9pp literacy gain",   tone: "violet" as const },
    { label: "14 staff need support", tone: "amber" as const },
    { label: "42 schools critical",  tone: "rose" as const },
  ],
};

// ────────── KPI Story Strip ────────────────────────────────────────────

export type StoryKpi = {
  key: string;
  label: string;
  hero: string;
  sub: string;
  detail: string;
  trend: string;
  trendUp: boolean;
  tone: "emerald" | "sky" | "violet" | "amber" | "rose";
};

export const storyKpis: StoryKpi[] = [
  {
    key: "completion",
    label: "Planned vs Completed",
    hero: "984",
    sub: "of 1,240 planned",
    detail: "79% completion rate",
    trend: "+6pp",
    trendUp: true,
    tone: "emerald",
  },
  {
    key: "verified",
    label: "Verified Delivery",
    hero: "812",
    sub: "IA verified",
    detail: "66% of planned · 83% of completed",
    trend: "+4pp",
    trendUp: true,
    tone: "sky",
  },
  {
    key: "school",
    label: "School Improvement",
    hero: "+0.6",
    sub: "avg SSA gain",
    detail: "324 improved · 71 declined",
    trend: "+0.2",
    trendUp: true,
    tone: "emerald",
  },
  {
    key: "literacy",
    label: "Literacy Outcome",
    hero: "+9pp",
    sub: "One Test gain",
    detail: "18,420 assessed · 62% at benchmark",
    trend: "+3pp",
    trendUp: true,
    tone: "violet",
  },
  {
    key: "risk",
    label: "Support & Risk",
    hero: "14",
    sub: "staff need support",
    detail: "42 schools critical · 118 SF IDs pending",
    trend: "-3",
    trendUp: true,
    tone: "amber",
  },
];

// ────────── Plan → Done → Verified funnel ──────────────────────────────

export type FunnelStage = {
  label: string;
  value: number;
  note: string;
  tone: "slate" | "sky" | "violet" | "emerald" | "rose";
};

export const deliveryFunnel: FunnelStage[] = [
  { label: "Planned",             value: 1240, note: "monthly plan activities", tone: "slate" },
  { label: "Completed",           value: 984,  note: "marked done by staff",    tone: "sky" },
  { label: "Salesforce Submitted",value: 880,  note: "SF ID entered",           tone: "violet" },
  { label: "IA Verified",         value: 812,  note: "official completed work", tone: "emerald" },
];

export const funnelReturned = { label: "Returned for correction", value: 72 };

// ────────── Staff Performance ──────────────────────────────────────────

export type StaffStatus = "On Track" | "Needs Attention" | "Support Needed" | "Critical";

export type StaffRow = {
  id: string;
  name: string;
  initials: string;
  programLead: string;
  district: string;
  planned: number;
  completed: number;
  verified: number;
  pendingVerification: number;
  overdue: number;
  salesforcePending: number;
  evidenceQuality: number; // %
  debriefRate: number; // %
  ssaGain: number;
  oneTestGain: number; // pp
  schoolsImproved: number;
  schoolsDeclined: number;
  status: StaffStatus;
  recommendedAction: string;
};

export const staffRows: StaffRow[] = [
  { id: "STF-PC", name: "Paul Chinyama", initials: "PC", programLead: "Daniel Mwangi", district: "Gulu",     planned: 64, completed: 50, verified: 41, pendingVerification: 9, overdue: 5,  salesforcePending: 12, evidenceQuality: 84, debriefRate: 92, ssaGain: 0.5,  oneTestGain: 7,  schoolsImproved: 9,  schoolsDeclined: 2, status: "Needs Attention", recommendedAction: "Schedule coaching" },
  { id: "STF-SM", name: "Sarah Mbeki",   initials: "SM", programLead: "Daniel Mwangi", district: "Lira",     planned: 58, completed: 54, verified: 50, pendingVerification: 4, overdue: 1,  salesforcePending: 3,  evidenceQuality: 93, debriefRate: 98, ssaGain: 0.9,  oneTestGain: 13, schoolsImproved: 12, schoolsDeclined: 1, status: "On Track",        recommendedAction: "Recognise & sustain" },
  { id: "STF-JO", name: "Joel Okello",   initials: "JO", programLead: "Daniel Mwangi", district: "Gulu",     planned: 60, completed: 38, verified: 26, pendingVerification: 12,overdue: 14, salesforcePending: 21, evidenceQuality: 61, debriefRate: 54, ssaGain: -0.2, oneTestGain: 1,  schoolsImproved: 3,  schoolsDeclined: 6, status: "Critical",        recommendedAction: "Open support plan" },
  { id: "STF-GA", name: "Grace Auma",    initials: "GA", programLead: "Ruth Wanjiru",  district: "Kitgum",   planned: 55, completed: 49, verified: 44, pendingVerification: 5, overdue: 2,  salesforcePending: 6,  evidenceQuality: 88, debriefRate: 90, ssaGain: 0.7,  oneTestGain: 10, schoolsImproved: 10, schoolsDeclined: 2, status: "On Track",        recommendedAction: "Recognise & sustain" },
  { id: "STF-MT", name: "Moses Tindi",   initials: "MT", programLead: "Ruth Wanjiru",  district: "Kitgum",   planned: 52, completed: 41, verified: 33, pendingVerification: 8, overdue: 6,  salesforcePending: 14, evidenceQuality: 72, debriefRate: 76, ssaGain: 0.3,  oneTestGain: 4,  schoolsImproved: 6,  schoolsDeclined: 4, status: "Needs Attention", recommendedAction: "Review plan" },
  { id: "STF-LN", name: "Lillian Nakato",initials: "LN", programLead: "Ruth Wanjiru",  district: "Pader",    planned: 50, completed: 47, verified: 43, pendingVerification: 4, overdue: 1,  salesforcePending: 4,  evidenceQuality: 90, debriefRate: 94, ssaGain: 0.8,  oneTestGain: 11, schoolsImproved: 11, schoolsDeclined: 0, status: "On Track",        recommendedAction: "Recognise & sustain" },
  { id: "STF-DK", name: "David Kato",    initials: "DK", programLead: "Daniel Mwangi", district: "Lira",     planned: 56, completed: 40, verified: 31, pendingVerification: 9, overdue: 8,  salesforcePending: 17, evidenceQuality: 67, debriefRate: 63, ssaGain: 0.1,  oneTestGain: 2,  schoolsImproved: 4,  schoolsDeclined: 5, status: "Support Needed",  recommendedAction: "Check route feasibility" },
  { id: "STF-RK", name: "Ruth Keb(Acam)",initials: "RK",programLead: "Ruth Wanjiru",  district: "Pader",    planned: 48, completed: 44, verified: 39, pendingVerification: 5, overdue: 2,  salesforcePending: 7,  evidenceQuality: 85, debriefRate: 88, ssaGain: 0.6,  oneTestGain: 8,  schoolsImproved: 8,  schoolsDeclined: 2, status: "On Track",        recommendedAction: "Recognise & sustain" },
];

// Monthly activity trend — planned / completed / verified.
export type TrendPoint = { label: string; planned: number; completed: number; verified: number };
export const activityTrend: TrendPoint[] = [
  { label: "Dec", planned: 210, completed: 168, verified: 132 },
  { label: "Jan", planned: 232, completed: 191, verified: 158 },
  { label: "Feb", planned: 248, completed: 205, verified: 171 },
  { label: "Mar", planned: 260, completed: 214, verified: 184 },
  { label: "Apr", planned: 255, completed: 209, verified: 178 },
  { label: "May", planned: 268, completed: 211, verified: 189 },
];

// Activity mix donut.
export type ActivitySlice = { label: string; count: number; color: string };
export const activityMix: ActivitySlice[] = [
  { label: "School Visits",       count: 312, color: "#10B981" },
  { label: "Training Follow-Ups", count: 198, color: "#3B82F6" },
  { label: "SSA Verification",    count: 146, color: "#8B5CF6" },
  { label: "Cluster Training",    count: 112, color: "#F59E0B" },
  { label: "Partner Monitoring",  count: 88,  color: "#F43F5E" },
  { label: "Special Projects",    count: 64,  color: "#0EA5E9" },
  { label: "Daily Debriefs",      count: 254, color: "#94A3B8" },
];

// Staff heatmap — readiness across 8 dimensions.
export type HeatLevel = "green" | "amber" | "red" | "gray";
export type HeatRow = { staff: string; cells: HeatLevel[] };
export const heatColumns = ["Visits", "Trainings", "Follow-ups", "SSA", "Salesforce", "Evidence", "Debrief", "Accountability"];
export const staffHeatmap: HeatRow[] = [
  { staff: "Sarah Mbeki",    cells: ["green","green","green","green","green","green","green","green"] },
  { staff: "Lillian Nakato", cells: ["green","green","green","green","green","green","green","amber"] },
  { staff: "Grace Auma",     cells: ["green","green","amber","green","green","green","green","green"] },
  { staff: "Ruth Keb",       cells: ["green","amber","green","green","amber","green","green","green"] },
  { staff: "Paul Chinyama",  cells: ["amber","green","amber","green","red","amber","green","amber"] },
  { staff: "Moses Tindi",    cells: ["amber","amber","amber","amber","red","amber","amber","green"] },
  { staff: "David Kato",     cells: ["red","amber","red","amber","red","red","red","amber"] },
  { staff: "Joel Okello",    cells: ["red","red","red","red","red","red","red","red"] },
];

// ────────── School Improvement ─────────────────────────────────────────

export const schoolImprovementSummary = {
  improved: 324,
  noChange: 96,
  declined: 71,
  noData: 38,
};

export type SchoolStatus = "Improving" | "Stable" | "Declining" | "Critical" | "Champion Candidate" | "No Current Data";

export type SchoolRow = {
  id: string;
  name: string;
  district: string;
  cluster: string;
  cceo: string;
  baselineSsa: number;
  currentSsa: number;
  baselineOneTest: number;
  currentOneTest: number;
  activitiesVerified: number;
  lastVisit: string;
  status: SchoolStatus;
  nextAction: string;
};

export const schoolRows: SchoolRow[] = [
  { id: "SCH-001", name: "St Mary's Primary",   district: "Gulu",   cluster: "Layibi",   cceo: "Sarah Mbeki",   baselineSsa: 6.1, currentSsa: 7.4, baselineOneTest: 48, currentOneTest: 64, activitiesVerified: 11, lastVisit: "May 22", status: "Champion Candidate", nextAction: "Nominate for Champion pipeline" },
  { id: "SCH-002", name: "Hope Junior School",  district: "Lira",   cluster: "Adyel",    cceo: "Sarah Mbeki",   baselineSsa: 5.4, currentSsa: 6.6, baselineOneTest: 41, currentOneTest: 53, activitiesVerified: 9,  lastVisit: "May 19", status: "Improving",          nextAction: "Continue coaching cadence" },
  { id: "SCH-003", name: "Bright Future P/S",   district: "Kitgum", cluster: "Pajimo",   cceo: "Grace Auma",    baselineSsa: 4.2, currentSsa: 5.5, baselineOneTest: 33, currentOneTest: 44, activitiesVerified: 12, lastVisit: "May 24", status: "Improving",          nextAction: "Verify Q2 SSA evidence" },
  { id: "SCH-004", name: "Unity Primary",       district: "Pader",  cluster: "Atanga",   cceo: "Lillian Nakato",baselineSsa: 6.8, currentSsa: 7.9, baselineOneTest: 55, currentOneTest: 68, activitiesVerified: 10, lastVisit: "May 20", status: "Champion Candidate", nextAction: "Nominate for Champion pipeline" },
  { id: "SCH-005", name: "Grace Memorial",      district: "Gulu",   cluster: "Layibi",   cceo: "Paul Chinyama", baselineSsa: 5.0, currentSsa: 5.2, baselineOneTest: 38, currentOneTest: 40, activitiesVerified: 5,  lastVisit: "May 12", status: "Stable",             nextAction: "Increase follow-up frequency" },
  { id: "SCH-006", name: "Acholi Quarter P/S",  district: "Gulu",   cluster: "Bardege",  cceo: "Joel Okello",   baselineSsa: 4.6, currentSsa: 4.1, baselineOneTest: 31, currentOneTest: 29, activitiesVerified: 2,  lastVisit: "Apr 28", status: "Declining",          nextAction: "Assign partner support" },
  { id: "SCH-007", name: "Kitgum Central P/S",  district: "Kitgum", cluster: "Pajimo",   cceo: "Moses Tindi",   baselineSsa: 3.8, currentSsa: 3.9, baselineOneTest: 27, currentOneTest: 28, activitiesVerified: 4,  lastVisit: "May 8",  status: "Critical",           nextAction: "Escalate to Program Lead" },
  { id: "SCH-008", name: "Lira Model School",   district: "Lira",   cluster: "Adyel",    cceo: "David Kato",    baselineSsa: 4.9, currentSsa: 4.4, baselineOneTest: 35, currentOneTest: 32, activitiesVerified: 3,  lastVisit: "Apr 30", status: "Declining",          nextAction: "Check route feasibility" },
  { id: "SCH-009", name: "Pader Hill Primary",  district: "Pader",  cluster: "Atanga",   cceo: "Ruth Keb",      baselineSsa: 5.7, currentSsa: 6.5, baselineOneTest: 44, currentOneTest: 54, activitiesVerified: 8,  lastVisit: "May 21", status: "Improving",          nextAction: "Continue coaching cadence" },
  { id: "SCH-010", name: "Northern Star P/S",   district: "Kitgum", cluster: "Pajimo",   cceo: "Grace Auma",    baselineSsa: 0,   currentSsa: 0,   baselineOneTest: 0,  currentOneTest: 0,  activitiesVerified: 0,  lastVisit: "—",      status: "No Current Data",    nextAction: "Schedule baseline SSA" },
];

// Improvement by district.
export type DistrictRow = { district: string; ssaGain: number; oneTestGain: number; improved: number; declined: number };
export const districtImprovement: DistrictRow[] = [
  { district: "Gulu",   ssaGain: 0.5, oneTestGain: 7,  improved: 78, declined: 22 },
  { district: "Lira",   ssaGain: 0.7, oneTestGain: 9,  improved: 91, declined: 14 },
  { district: "Kitgum", ssaGain: 0.6, oneTestGain: 8,  improved: 84, declined: 18 },
  { district: "Pader",  ssaGain: 0.8, oneTestGain: 11, improved: 71, declined: 9  },
];

// ────────── SSA Analytics ──────────────────────────────────────────────

export type SsaTrendPoint = { label: string; score: number };
export const ssaTrend: SsaTrendPoint[] = [
  { label: "Oct", score: 5.6 },
  { label: "Nov", score: 5.8 },
  { label: "Dec", score: 6.0 },
  { label: "Jan", score: 6.1 },
  { label: "Feb", score: 6.3 },
  { label: "Mar", score: 6.5 },
];

export type Intervention = {
  label: string;
  baseline: number;
  current: number;
};
export const ssaInterventions: Intervention[] = [
  { label: "Leadership",            baseline: 5.4, current: 6.7 },
  { label: "Teaching Environment",  baseline: 5.1, current: 6.2 },
  { label: "Learning Environment",  baseline: 4.8, current: 6.0 },
  { label: "Fees / Budget",         baseline: 5.9, current: 6.4 },
  { label: "Govt Requirements",     baseline: 6.2, current: 7.1 },
  { label: "Christ-like Behaviour", baseline: 6.5, current: 7.3 },
  { label: "Word of God",           baseline: 6.0, current: 6.9 },
  { label: "Enrollment",            baseline: 5.3, current: 5.8 },
];

export const ssaMovement = {
  redToAmber: 46,
  amberToGreen: 58,
  greenHeld: 132,
  droppedBack: 27,
};

export const ssaRiskBuckets = [
  { label: "Critical (0–4.9)",   count: 42,  tone: "rose"    as const },
  { label: "Needs Support (5–6.9)", count: 168, tone: "amber" as const },
  { label: "Good (7–8.4)",       count: 214, tone: "emerald" as const },
  { label: "Strong (8.5–10)",    count: 63,  tone: "sky"     as const },
];

export const ssaDataGaps = {
  noCurrentFy: 38,
  needsVerification: 24,
  oldSsaOnly: 17,
};

// ────────── One Test Literacy ──────────────────────────────────────────

export const oneTestKpis = [
  { label: "Learners Assessed",      value: "18,420", tone: "sky"     as const },
  { label: "Literacy Gain",          value: "+9pp",   tone: "violet"  as const },
  { label: "At Benchmark",           value: "62%",    tone: "emerald" as const },
  { label: "Below Benchmark",        value: "4,812",  tone: "rose"    as const },
  { label: "Schools Improved",       value: "312",    tone: "emerald" as const },
  { label: "Schools Declined",       value: "47",     tone: "amber"   as const },
];

export type LiteracyPoint = { label: string; score: number };
export const literacyTrend: LiteracyPoint[] = [
  { label: "Baseline", score: 41 },
  { label: "Midline",  score: 48 },
  { label: "Endline",  score: 50 },
];

export const benchmarkBands = [
  { label: "Below Basic", count: 2140, color: "#F43F5E" },
  { label: "Basic",       count: 4830, color: "#F59E0B" },
  { label: "Proficient",  count: 8120, color: "#10B981" },
  { label: "Strong",      count: 3330, color: "#0EA5E9" },
];

export type ClassRow = { grade: string; baseline: number; current: number };
export const literacyByClass: ClassRow[] = [
  { grade: "P1", baseline: 32, current: 44 },
  { grade: "P2", baseline: 36, current: 49 },
  { grade: "P3", baseline: 40, current: 52 },
  { grade: "P4", baseline: 44, current: 55 },
  { grade: "P5", baseline: 47, current: 56 },
  { grade: "P6", baseline: 51, current: 60 },
  { grade: "P7", baseline: 55, current: 63 },
];

// SSA → Literacy correlation.
export const ssaLiteracyCorrelation = [
  { band: "SSA gain +0.5 or more", literacyGain: 11, schools: 188, tone: "emerald" as const },
  { band: "SSA flat (−0.2 to +0.4)", literacyGain: 3, schools: 142, tone: "amber"   as const },
  { band: "SSA declining",          literacyGain: -2, schools: 59,  tone: "rose"    as const },
];

// Scatter points: SSA change (x) vs literacy change (y).
export type ScatterPoint = { x: number; y: number; district: string };
export const ssaLiteracyScatter: ScatterPoint[] = [
  { x: 1.3, y: 16, district: "Gulu" }, { x: 1.2, y: 13, district: "Lira" },
  { x: 1.1, y: 11, district: "Kitgum" }, { x: 0.9, y: 12, district: "Pader" },
  { x: 0.8, y: 10, district: "Lira" }, { x: 0.7, y: 8, district: "Gulu" },
  { x: 0.6, y: 9, district: "Pader" }, { x: 0.5, y: 7, district: "Kitgum" },
  { x: 0.3, y: 4, district: "Gulu" }, { x: 0.2, y: 3, district: "Lira" },
  { x: 0.1, y: 2, district: "Kitgum" }, { x: -0.2, y: -1, district: "Gulu" },
  { x: -0.4, y: -3, district: "Lira" }, { x: -0.5, y: -2, district: "Kitgum" },
];

// ────────── Activity-to-Outcome effectiveness ──────────────────────────

export type EffectivenessRow = {
  activity: string;
  verified: number;
  ssaGain: number;
  oneTestGain: number;
  schoolsImprovedPct: number;
  evidenceQuality: number;
};
export const activityEffectiveness: EffectivenessRow[] = [
  { activity: "In-School Coaching",  verified: 218, ssaGain: 0.8, oneTestGain: 12, schoolsImprovedPct: 76, evidenceQuality: 89 },
  { activity: "Training Follow-Up",  verified: 164, ssaGain: 0.6, oneTestGain: 9,  schoolsImprovedPct: 68, evidenceQuality: 85 },
  { activity: "Cluster Training",    verified: 96,  ssaGain: 0.5, oneTestGain: 7,  schoolsImprovedPct: 61, evidenceQuality: 82 },
  { activity: "SSA Verification",    verified: 132, ssaGain: 0.3, oneTestGain: 4,  schoolsImprovedPct: 44, evidenceQuality: 91 },
  { activity: "Core School Visit",   verified: 88,  ssaGain: 0.7, oneTestGain: 10, schoolsImprovedPct: 72, evidenceQuality: 87 },
  { activity: "Partner Follow-Up",   verified: 74,  ssaGain: 0.4, oneTestGain: 6,  schoolsImprovedPct: 55, evidenceQuality: 73 },
  { activity: "Special Project Visit",verified: 40, ssaGain: 0.5, oneTestGain: 8,  schoolsImprovedPct: 60, evidenceQuality: 80 },
];

// ────────── Partner Delivery ───────────────────────────────────────────

export type PartnerStatus = "Strong Partner" | "Reliable" | "Needs Coaching" | "High Return Rate" | "At Risk";
export type PartnerRow = {
  name: string;
  assignedSchools: number;
  completed: number;
  verified: number;
  returned: number;
  evidenceQuality: number;
  ssaGain: number;
  oneTestGain: number;
  status: PartnerStatus;
};
export const partnerRows: PartnerRow[] = [
  { name: "Hope Education Trust",   assignedSchools: 24, completed: 22, verified: 20, returned: 2,  evidenceQuality: 91, ssaGain: 0.7, oneTestGain: 10, status: "Strong Partner" },
  { name: "Northern Light NGO",    assignedSchools: 18, completed: 16, verified: 14, returned: 2,  evidenceQuality: 84, ssaGain: 0.5, oneTestGain: 7,  status: "Reliable" },
  { name: "Acholi Dev Initiative", assignedSchools: 21, completed: 15, verified: 10, returned: 5,  evidenceQuality: 68, ssaGain: 0.3, oneTestGain: 4,  status: "Needs Coaching" },
  { name: "Rural Schools Alliance",assignedSchools: 16, completed: 12, verified: 6,  returned: 6,  evidenceQuality: 59, ssaGain: 0.1, oneTestGain: 2,  status: "High Return Rate" },
  { name: "Bright Path Partners",  assignedSchools: 14, completed: 7,  verified: 4,  returned: 3,  evidenceQuality: 52, ssaGain: -0.1,oneTestGain: 1,  status: "At Risk" },
];

// ────────── Evidence Quality ───────────────────────────────────────────

export const evidenceQuality = {
  score: 81,
  breakdown: [
    { label: "Salesforce ID submitted", pct: 88, tone: "emerald" as const },
    { label: "Evidence uploaded",       pct: 84, tone: "emerald" as const },
    { label: "GPS / time captured",     pct: 76, tone: "amber"   as const },
    { label: "IA verified",             pct: 66, tone: "amber"   as const },
    { label: "Partner form uploaded",   pct: 71, tone: "amber"   as const },
    { label: "Returned evidence",       pct: 8,  tone: "rose"    as const },
  ],
};

// ────────── Funding-to-Delivery ────────────────────────────────────────

export const fundingSummary = {
  approved: "UGX 96.0M",
  disbursed: "UGX 74.2M",
  received: "UGX 71.8M",
  verifiedActivities: 812,
  costPerVerified: "UGX 91,379",
  accountabilityPending: 23,
  netsuitePending: 118,
  reimbursementsDue: 9,
  balanceReturnsDue: 7,
  weeksBlocked: 4,
};

export type FundingFlowStage = { label: string; value: string; pct: number; tone: "slate" | "sky" | "violet" | "emerald" };
export const fundingFlow: FundingFlowStage[] = [
  { label: "Funds Approved",   value: "UGX 96.0M", pct: 100, tone: "slate" },
  { label: "Funds Disbursed",  value: "UGX 74.2M", pct: 77,  tone: "sky" },
  { label: "Activities Funded",value: "984",       pct: 79,  tone: "violet" },
  { label: "Verified Delivery",value: "812",       pct: 66,  tone: "emerald" },
];

// ────────── Daily Debrief Barriers ─────────────────────────────────────

export type BarrierRow = { label: string; count: number; trend: "up" | "down" | "flat" };
export const barrierRows: BarrierRow[] = [
  { label: "School unavailable",   count: 64, trend: "up" },
  { label: "Route / transport",    count: 51, trend: "up" },
  { label: "Funding delay",        count: 38, trend: "down" },
  { label: "Weather",              count: 29, trend: "flat" },
  { label: "Partner delay",        count: 22, trend: "down" },
  { label: "Salesforce issue",     count: 18, trend: "flat" },
  { label: "Staff capacity",       count: 14, trend: "down" },
  { label: "Community event",      count: 11, trend: "flat" },
];

export const barrierInsight =
  "Most missed activities this month were caused by school availability and route difficulty — not staff inactivity. Performance scoring is adjusted for verified field barriers.";

// ────────── Support & Risk Signals ─────────────────────────────────────

export const supportSummary = {
  onTrack: 4,
  needsAttention: 2,
  supportNeeded: 1,
  critical: 1,
};
