// Country Director executive dashboard — mock data layer.
// Numbers are illustrative; shapes match what the real backend will return so
// every card swaps to db.* without UI changes.

// ────────── KPI row (8 cards) ──────────

export type CountryKpi = {
  key: string;
  label: string;
  value: string;
  trend: { delta: string; tone: "up" | "down"; suffix?: string };
  sub?: string;
  icon:
    | "target"
    | "school"
    | "shield"
    | "users"
    | "cloud"
    | "wallet"
    | "pieChart"
    | "alertTriangle";
  iconTone: "edify" | "green" | "amber" | "red" | "blue" | "violet";
  spark: { seed: number; trend: "up" | "down" };
};

export const countryKpis: CountryKpi[] = [
  { key: "country_target",  label: "Country Target Progress", value: "72%",       trend: { delta: "5 pp",   tone: "up", suffix: "vs Apr 2025" },     icon: "target",         iconTone: "edify",  spark: { seed: 1, trend: "up" } },
  { key: "schools_served",  label: "Active Schools Served",   value: "28,450",    trend: { delta: "1,134",  tone: "up", suffix: "vs Apr 2025" },     icon: "school",         iconTone: "edify",  spark: { seed: 2, trend: "up" } },
  { key: "core_on_track",   label: "Core Schools On Track",   value: "68%",       trend: { delta: "6 pp",   tone: "up", suffix: "vs Apr 2025" },     icon: "shield",         iconTone: "green",  spark: { seed: 3, trend: "up" } },
  { key: "staff_prod",      label: "Staff Productivity",      value: "84%",       trend: { delta: "4 pp",   tone: "up", suffix: "vs Apr 2025" },     icon: "users",          iconTone: "edify",  spark: { seed: 4, trend: "up" } },
  { key: "sf_compliance",   label: "Salesforce Compliance",   value: "87%",       trend: { delta: "3 pp",   tone: "up", suffix: "vs Apr 2025" },     icon: "cloud",          iconTone: "edify",  spark: { seed: 5, trend: "up" } },
  { key: "fund_pending",    label: "Pending Fund Requests",   value: "154",       trend: { delta: "UGX 5.29B pending", tone: "down" },               icon: "wallet",         iconTone: "amber",  spark: { seed: 6, trend: "up" } },
  { key: "budget_util",     label: "Budget Utilization",      value: "64%",       trend: { delta: "UGX 77.6B / 121.1B", tone: "up" },                icon: "pieChart",       iconTone: "edify",  spark: { seed: 7, trend: "up" } },
  { key: "high_risk_teams", label: "High-Risk Teams",         value: "16",        trend: { delta: "2",      tone: "up", suffix: "vs Apr 2025" },     icon: "alertTriangle",  iconTone: "red",    spark: { seed: 8, trend: "down" } },
];

// ────────── Leadership attention row (3 alerts) ──────────

export type LeadershipAlert = {
  id: string;
  title: string;
  body: string;
  cta: string;
  href: string;
  tone: "amber" | "red" | "blue";
  icon: "alertTriangle" | "database" | "wallet";
};

export const leadershipAlerts: LeadershipAlert[] = [
  {
    id: "alert-region",
    title: "1 Region Behind Target",
    body: "West is at 65% vs national 72% target progress.",
    cta: "View Regional Performance",
    href: "/reports",
    tone: "amber",
    icon: "alertTriangle",
  },
  {
    id: "alert-sf",
    title: "High Salesforce Backlog",
    body: "7,842 Salesforce IDs pending action across 18 teams.",
    cta: "Inspect Backlog",
    href: "#operational-risk",
    tone: "blue",
    icon: "database",
  },
  {
    id: "alert-funds",
    title: "154 Fund Requests Pending",
    body: "UGX 5.29B awaiting Country Director approval.",
    cta: "Review Approvals",
    href: "/fund-requests",
    tone: "amber",
    icon: "wallet",
  },
];

// ────────── Country performance overview (mixed bar + line, 11 months) ──────────

export type MonthlyPerformance = {
  month: string;
  planned: number;
  completed: number;
  verified: number;
  targetPct: number;
};

export const monthlyPerformance: MonthlyPerformance[] = [
  { month: "Jul 2024", planned: 50000, completed: 32000, verified: 28000, targetPct: 70 },
  { month: "Aug 2024", planned: 58000, completed: 38000, verified: 34000, targetPct: 75 },
  { month: "Sep 2024", planned: 52000, completed: 36000, verified: 33000, targetPct: 72 },
  { month: "Oct 2024", planned: 64000, completed: 46000, verified: 42000, targetPct: 78 },
  { month: "Nov 2024", planned: 50000, completed: 36000, verified: 32000, targetPct: 70 },
  { month: "Dec 2024", planned: 30000, completed: 22000, verified: 19000, targetPct: 28 },
  { month: "Jan 2025", planned: 46000, completed: 36000, verified: 32000, targetPct: 56 },
  { month: "Feb 2025", planned: 64000, completed: 48000, verified: 44000, targetPct: 76 },
  { month: "Mar 2025", planned: 58000, completed: 42000, verified: 38000, targetPct: 70 },
  { month: "Apr 2025", planned: 64000, completed: 52000, verified: 47000, targetPct: 75 },
  { month: "May 2025", planned: 70000, completed: 58000, verified: 52000, targetPct: 78 },
];

// ────────── Regional performance ranking ──────────

export type RegionalPerformance = {
  rank: number;
  region: string;
  achievementPct: number;
};

export const regionalPerformance: RegionalPerformance[] = [
  { rank: 1, region: "Central", achievementPct: 88 },
  { rank: 2, region: "East",    achievementPct: 79 },
  { rank: 3, region: "North",   achievementPct: 72 },
  { rank: 4, region: "West",    achievementPct: 65 },
];

export const nationalAverageAchievement = 72;

// ────────── Country Program Leads performance ──────────

export type ProgramLeadRow = {
  id: string;
  name: string;
  initials: string;
  region: string;
  teamTargetPct: number;
  staffUnderThem: number;
  activitiesPlanned: number;
  verifiedActivities: number;
  salesforcePending: number;
  backlog: number;
  riskStatus: "On Track" | "Watch" | "High Risk";
};

export const programLeads: ProgramLeadRow[] = [
  { id: "pl-1", name: "James O. Akena",   initials: "JA", region: "Central",   teamTargetPct: 88, staffUnderThem: 124, activitiesPlanned: 18432, verifiedActivities: 14920, salesforcePending: 342,  backlog: 1124, riskStatus: "On Track" },
  { id: "pl-2", name: "Grace N. Apio",    initials: "GA", region: "East",      teamTargetPct: 79, staffUnderThem: 98,  activitiesPlanned: 15211, verifiedActivities: 11830, salesforcePending: 412,  backlog: 1542, riskStatus: "On Track" },
  { id: "pl-3", name: "Peter M. Odong",   initials: "PO", region: "North",     teamTargetPct: 72, staffUnderThem: 87,  activitiesPlanned: 12954, verifiedActivities: 9324,  salesforcePending: 821,  backlog: 2015, riskStatus: "Watch" },
  { id: "pl-4", name: "Sarah K. Nabirye", initials: "SN", region: "West",      teamTargetPct: 65, staffUnderThem: 103, activitiesPlanned: 14105, verifiedActivities: 9210,  salesforcePending: 1126, backlog: 2346, riskStatus: "Watch" },
  { id: "pl-5", name: "Brian T. Okello",  initials: "BO", region: "North",     teamTargetPct: 58, staffUnderThem: 76,  activitiesPlanned: 10342, verifiedActivities: 5987,  salesforcePending: 2018, backlog: 3112, riskStatus: "High Risk" },
  { id: "pl-6", name: "Esther L. Nakato", initials: "EN", region: "North",     teamTargetPct: 46, staffUnderThem: 59,  activitiesPlanned: 7842,  verifiedActivities: 3248,  salesforcePending: 3123, backlog: 4210, riskStatus: "High Risk" },
];

// ────────── Fund Approval & Finance Snapshot ──────────

export type PendingFundRequest = {
  id: string;
  region: string;
  amountLabel: string;
  activitiesCovered: number;
  stage: "Review";
};

export const pendingFundRequests: PendingFundRequest[] = [
  { id: "fr-north",   region: "North",   amountLabel: "UGX 1.24B", activitiesCovered: 3452, stage: "Review" },
  { id: "fr-east",    region: "East",    amountLabel: "UGX 1.05B", activitiesCovered: 2867, stage: "Review" },
  { id: "fr-west",    region: "West",    amountLabel: "UGX 870M",  activitiesCovered: 1982, stage: "Review" },
  { id: "fr-central", region: "Central", amountLabel: "UGX 980M",  activitiesCovered: 2154, stage: "Review" },
];

export const fundedNotCompleted = {
  totalLabel: "UGX 8.42B",
  activities: 1246,
  overdue: 782,
  partial: 312,
  notStarted: 152,
};

// ────────── Operational Risk & Backlog (6 cards) ──────────

export type OperationalRiskTile = {
  key: string;
  label: string;
  value: string;
  delta: string;
  deltaTone: "up" | "down";
  icon: "database" | "rotateCcw" | "schoolX" | "graduationCap" | "shieldAlert" | "users";
  tone: "red" | "amber" | "yellow" | "violet" | "rose" | "lavender";
};

export const operationalRisks: OperationalRiskTile[] = [
  { key: "sf_overdue",     label: "Overdue Salesforce IDs",  value: "7,842", delta: "1,122",  deltaTone: "up", icon: "database",      tone: "red"      },
  { key: "verif_returned", label: "Returned Verifications",  value: "1,126", delta: "216",    deltaTone: "up", icon: "rotateCcw",     tone: "amber"    },
  { key: "no_recent_visit",label: "Schools No Recent Visit", value: "1,458", delta: "342",    deltaTone: "up", icon: "schoolX",       tone: "yellow"   },
  { key: "no_training",    label: "Schools No Training",     value: "1,237", delta: "298",    deltaTone: "up", icon: "graduationCap", tone: "violet"   },
  { key: "core_behind",    label: "Core Schools Behind",     value: "842",   delta: "124",    deltaTone: "up", icon: "shieldAlert",   tone: "rose"     },
  { key: "leave_conflict", label: "Leave / Conflict Alerts", value: "214",   delta: "28",     deltaTone: "up", icon: "users",         tone: "lavender" },
];

// ────────── School & SSA Intelligence (8 interventions + Overall) ──────────
//
// The product document defines the 8 SSA intervention areas:
//   • Christ-like Behavior
//   • Exposure to the Word of God
//   • Fees / Budget / Accounts
//   • Government Requirements
//   • Leadership Best Practice
//   • Learning Environment
//   • Teaching Environment
//   • Enrollment
// The screenshot abbreviates these to fit 8 columns + Overall.

export type SsaIntervention =
  | "CLB"  // Christ-like Behavior
  | "WoG"  // Word of God
  | "F&A"  // Fees / Budget / Accounts
  | "GOV"  // Government Requirements
  | "LDR"  // Leadership Best Practice
  | "LEnv" // Learning Environment
  | "TEnv" // Teaching Environment
  | "ENR"; // Enrollment

export const ssaInterventionFullName: Record<SsaIntervention, string> = {
  CLB:  "Christ-like Behavior",
  WoG:  "Exposure to the Word of God",
  "F&A":"Fees / Budget / Accounts",
  GOV:  "Government Requirements",
  LDR:  "Leadership Best Practice",
  LEnv: "Learning Environment",
  TEnv: "Teaching Environment",
  ENR:  "Enrollment",
};

export const ssaInterventionOrder: SsaIntervention[] = ["CLB", "WoG", "F&A", "GOV", "LDR", "LEnv", "TEnv", "ENR"];

export type SsaRegionalRow = {
  region: string;
  scores: Record<SsaIntervention, number>;
  overall: number;
};

export const ssaIntelligence: SsaRegionalRow[] = [
  { region: "Central", scores: { CLB: 82, WoG: 78, "F&A": 74, GOV: 80, LDR: 76, LEnv: 71, TEnv: 83, ENR: 77 }, overall: 77 },
  { region: "East",    scores: { CLB: 75, WoG: 70, "F&A": 65, GOV: 72, LDR: 69, LEnv: 62, TEnv: 74, ENR: 68 }, overall: 69 },
  { region: "North",   scores: { CLB: 71, WoG: 66, "F&A": 60, GOV: 68, LDR: 64, LEnv: 58, TEnv: 70, ENR: 63 }, overall: 65 },
  { region: "West",    scores: { CLB: 68, WoG: 62, "F&A": 56, GOV: 64, LDR: 60, LEnv: 54, TEnv: 66, ENR: 59 }, overall: 61 },
];

// ────────── Priority schools needing urgent attention ──────────
// Priority order from the product doc:
//   1. SSA performance (lowest first) — primary driver
//   2. Becoming inactive / inactive
//   3. No visit
//   4. No training
//   5. Neither visit nor training

export type PriorityIssue = "SSA Weakness" | "No Visit" | "No Training";

export type DirectorPriorityRow = {
  id: string;
  school: string;
  region: string;
  ssaScore: number;
  issues: PriorityIssue[];
  risk: "High" | "Medium" | "Low";
  action: "Inspect" | "Review";
};

export const priorityDirectorSchools: DirectorPriorityRow[] = [
  { id: "ps-1", school: "St. Mary's PS",     region: "North", ssaScore: 41, issues: ["No Visit", "No Training"],     risk: "High",   action: "Inspect" },
  { id: "ps-2", school: "Arua Central PS",   region: "North", ssaScore: 38, issues: ["SSA Weakness", "No Visit"],    risk: "High",   action: "Inspect" },
  { id: "ps-3", school: "Koboko PS",         region: "North", ssaScore: 44, issues: ["No Training"],                  risk: "High",   action: "Inspect" },
  { id: "ps-4", school: "Napak Pri. Sch.",   region: "North", ssaScore: 36, issues: ["No Visit", "No Training"],     risk: "High",   action: "Inspect" },
  { id: "ps-5", school: "Lokichoggio PS",    region: "North", ssaScore: 39, issues: ["SSA Weakness"],                  risk: "Medium", action: "Review"  },
];

// ────────── Quick Leadership Actions (6 nav cards) ──────────

export type LeadershipActionTile = {
  key: string;
  title: string;
  subtitle: string;
  icon: "wallet" | "alertTriangle" | "database" | "shieldAlert" | "target" | "fileText";
  href: string;
  tone: "edify";
};

export const leadershipActions: LeadershipActionTile[] = [
  { key: "review_funds",   title: "Review Fund Requests",      subtitle: "154 pending approvals",    icon: "wallet",        href: "/approvals",         tone: "edify" },
  { key: "high_risk",      title: "View High-Risk Regions",    subtitle: "2 regions need attention", icon: "alertTriangle", href: "/reports",           tone: "edify" },
  { key: "sf_backlog",     title: "Inspect Salesforce Backlog",subtitle: "7,842 pending records",   icon: "database",      href: "/quality-checks",   tone: "edify" },
  { key: "team_targets",   title: "Review Team Targets",       subtitle: "Individual achievement",   icon: "target",        href: "/team-targets",      tone: "edify" },
  { key: "analytics",      title: "Country Analytics",         subtitle: "Staff & SSA oversight",  icon: "shieldAlert",   href: "/analytics",         tone: "edify" },
  { key: "country_report", title: "Open Country Report",       subtitle: "Comprehensive overview",   icon: "fileText",      href: "/reports",            tone: "edify" },
];

// ────────── Director identity (sidebar + header) ──────────

export const directorUser = {
  name: "Daniel Mwangi",
  initials: "DM",
  role: "Country Director",
  online: true,
  scope: "Uganda",
};

export const directorHeader = {
  breadcrumb: ["Home", "Executive Dashboard"] as const,
  title: "Country Director Dashboard",
  subtitle: "National program performance, approvals, targets, compliance, and operational risk.",
  filters: {
    financialYear: "FY 2024/25",
    month: "May 2025",
    countryRegion: "Uganda",
  },
  searchPlaceholder: "Search staff, partners, regions…",
};

export const notificationCount = 12;
