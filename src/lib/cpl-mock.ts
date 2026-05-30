// Country Program Lead executive dashboard — mock data layer.
// Numbers are illustrative; shapes match what the real backend will return so
// every card swaps to db.* without UI changes.
//
// Role boundary (per product doc):
//   Country Program Leads APPROVE PLANS only.
//   Fund approval is a separate flow: Program Accountant → Country Director → RVP.

// ────────── KPI row (8 cards) ──────────

export type TeamKpi = {
  key: string;
  // `label` is the analytical name (eyebrow). Kept for users who think
  // in operational terms (Salesforce Compliance, Team Backlog).
  label: string;
  // `humanLabel` is the headline that replaces the number-as-noun.
  // Tells the user *why this number matters in human terms*. When
  // present, the tile renders this above the analytical label as the
  // primary story; the label drops to a subdued eyebrow.
  humanLabel?: string;
  value: string;
  trend: { delta: string; tone: "up" | "down"; suffix?: string };
  sub?: string;
  icon:
    | "target"
    | "users"
    | "clipboardList"
    | "calendarCheck"
    | "shieldCheck"
    | "layers"
    | "wallet"
    | "alertTriangle";
  iconTone: "edify" | "green" | "amber" | "red" | "blue" | "violet";
  spark: { seed: number; trend: "up" | "down" };
};

// Voice rule: lead with the human consequence, not the metric. Numbers
// stay the same — what changes is what story they tell when a CPL
// glances at the row Monday morning.
export const teamKpis: TeamKpi[] = [
  { key: "team_target",   label: "Team Target Progress",   humanLabel: "Of this month's plan, delivered.",     value: "72%",       trend: { delta: "6 pp",  tone: "up",   suffix: "vs Apr 2025" },  icon: "target",        iconTone: "edify", spark: { seed: 11, trend: "up" } },
  { key: "cceos_track",   label: "CCEOs On Track",          humanLabel: "Of your team is hitting pace.",        value: "68%",       trend: { delta: "7 pp",  tone: "up",   suffix: "vs Apr 2025" },  icon: "users",         iconTone: "edify", spark: { seed: 12, trend: "up" } },
  { key: "plans_pending", label: "Plans Awaiting Approval", humanLabel: "Plans need your eyes today.",          value: "28",        trend: { delta: "4",     tone: "up",   suffix: "vs last week" }, icon: "clipboardList", iconTone: "amber", spark: { seed: 13, trend: "down" } },
  { key: "activities_wk", label: "Children Reached",        humanLabel: "Children reached this week.",          value: "18,400",    trend: { delta: "9%",    tone: "up",   suffix: "vs last week" }, icon: "calendarCheck", iconTone: "edify", spark: { seed: 14, trend: "up" } },
  { key: "sf_compliance", label: "Salesforce Compliance",   humanLabel: "Of field work, formally logged.",      value: "87%",       trend: { delta: "5 pp",  tone: "up",   suffix: "vs Apr 2025" },  icon: "shieldCheck",   iconTone: "green", spark: { seed: 15, trend: "up" } },
  { key: "team_backlog",  label: "Team Backlog",            humanLabel: "Activities waiting to be picked up.",  value: "164",       trend: { delta: "18",    tone: "down", suffix: "vs last week" }, icon: "layers",        iconTone: "amber", spark: { seed: 16, trend: "down" } },
  { key: "fund_request",  label: "Monthly Fund Request",    humanLabel: "Funds in the field, working.",         value: "UGX 8.42B", trend: { delta: "68%",   tone: "up",   suffix: "utilized" },     icon: "wallet",        iconTone: "blue",  spark: { seed: 17, trend: "up" } },
  { key: "high_risk",     label: "High-Risk Schools",       humanLabel: "Schools we're losing. Don't.",         value: "46",        trend: { delta: "6",     tone: "up",   suffix: "vs Apr 2025" },  icon: "alertTriangle", iconTone: "red",   spark: { seed: 18, trend: "down" } },
];

// ────────── Leadership attention row (3 alerts) ──────────

export type CplAlert = {
  id: string;
  title: string;
  body: string;
  cta: string;
  href: string;
  tone: "amber" | "red" | "blue";
  icon: "users" | "database" | "alertTriangle";
};

export const cplLeadershipAlerts: CplAlert[] = [
  {
    id: "alert-overload",
    title: "Staff Overload Warning",
    body: "14 staff have >120% workload capacity. Action required to rebalance routes.",
    cta: "View Overloaded Staff",
    href: "#workload",
    tone: "amber",
    icon: "users",
  },
  {
    id: "alert-sf-backlog",
    title: "Salesforce Backlog Warning",
    body: "164 Salesforce IDs pending action > 7 days. Compliance risk increasing.",
    cta: "Review Backlog",
    href: "#backlog-snapshot",
    tone: "blue",
    icon: "database",
  },
  {
    id: "alert-high-risk",
    title: "High-Risk Schools / Regions",
    body: "46 schools across 3 regions flagged as high risk. Immediate follow-up needed.",
    cta: "View High-Risk Schools",
    href: "#urgent-schools",
    tone: "red",
    icon: "alertTriangle",
  },
];

// ────────── Team performance overview (mixed bar + line, 12 months) ──────────

export type TeamPerformanceMonth = {
  month: string;
  planned: number;
  completed: number;
  verified: number;
  targetPct: number;
};

export const teamPerformance: TeamPerformanceMonth[] = [
  { month: "Jun 2024", planned: 50000, completed: 32000, verified: 28000, targetPct: 62 },
  { month: "Jul 2024", planned: 55000, completed: 36000, verified: 32000, targetPct: 68 },
  { month: "Aug 2024", planned: 60000, completed: 42000, verified: 38000, targetPct: 72 },
  { month: "Sep 2024", planned: 56000, completed: 40000, verified: 36000, targetPct: 70 },
  { month: "Oct 2024", planned: 58000, completed: 42000, verified: 38000, targetPct: 71 },
  { month: "Nov 2024", planned: 50000, completed: 36000, verified: 32000, targetPct: 65 },
  { month: "Dec 2024", planned: 32000, completed: 22000, verified: 19000, targetPct: 32 },
  { month: "Jan 2025", planned: 46000, completed: 36000, verified: 32000, targetPct: 56 },
  { month: "Feb 2025", planned: 60000, completed: 46000, verified: 42000, targetPct: 74 },
  { month: "Mar 2025", planned: 56000, completed: 42000, verified: 38000, targetPct: 70 },
  { month: "Apr 2025", planned: 64000, completed: 50000, verified: 46000, targetPct: 76 },
  { month: "May 2025", planned: 70000, completed: 56000, verified: 52000, targetPct: 78 },
];

// ────────── My Personal Targets (4 ring cards + overall bar) ──────────

export type PersonalTarget = {
  key: string;
  label: string;
  current: number;
  total: number;
  pct: number;
  delta: string;
  icon: "users" | "clipboardList" | "userCheck" | "wallet";
};

export const personalTargets: PersonalTarget[] = [
  { key: "supervision_visits", label: "Supervision Visits",   current: 42, total: 60, pct: 70, delta: "8 vs Apr",  icon: "users" },
  { key: "plan_approvals",     label: "Plan Approvals",       current: 28, total: 40, pct: 70, delta: "6 vs Apr",  icon: "clipboardList" },
  { key: "team_reviews",       label: "Team Reviews",         current: 36, total: 50, pct: 72, delta: "7 vs Apr",  icon: "userCheck" },
  { key: "fund_reviewed",      label: "Fund Requests Reviewed", current: 8, total: 12, pct: 67, delta: "2 vs Apr",  icon: "wallet" },
];

export const personalOverall = {
  pct: 70,
  trend: "6 pp vs Apr 2025",
};

// ────────── CPL Personal Field Work ──────────
//
// Country Program Leads don't only manage CCEOs — they also conduct
// school visits, deliver trainings, run SSA assessments, and submit
// daily field debriefs themselves. The cards below surface that direct
// work next to the team-management KPIs so the dashboard reflects the
// full role.

export type CplFieldworkTile = {
  key: string;
  label: string;
  value: number;
  total: number;
  caption: string;
  trendDelta: string;
  trendTone: "up" | "down";
  icon: "schoolVisit" | "training" | "ssa" | "debrief" | "follow";
  tone: "edify" | "green" | "amber" | "violet" | "blue";
};

export const cplPersonalFieldwork: CplFieldworkTile[] = [
  { key: "visits",     label: "School Visits I conducted",     value: 14, total: 18, caption: "78% of target", trendDelta: "3 vs Apr",  trendTone: "up",   icon: "schoolVisit", tone: "edify"  },
  { key: "trainings",  label: "Trainings I delivered",         value: 6,  total: 8,  caption: "75% of target", trendDelta: "1 vs Apr",  trendTone: "up",   icon: "training",    tone: "violet" },
  { key: "ssa",        label: "SSAs I conducted",              value: 9,  total: 12, caption: "75% of target", trendDelta: "2 vs Apr",  trendTone: "up",   icon: "ssa",         tone: "green"  },
  { key: "follow_ups", label: "Follow-Up visits I closed",     value: 5,  total: 8,  caption: "63% of target", trendDelta: "1 vs Apr",  trendTone: "down", icon: "follow",      tone: "amber"  },
  { key: "debriefs",   label: "Daily Field Debriefs I filed",  value: 17, total: 20, caption: "85% of target", trendDelta: "4 vs Apr",  trendTone: "up",   icon: "debrief",     tone: "blue"   },
];

export type CplFieldworkUpcoming = {
  key: string;
  type: "School Visit" | "Cluster Training" | "SSA" | "Follow-Up Visit";
  title: string;
  cluster: string;
  date: string;
  weekLabel: string;
};

export const cplFieldworkUpcoming: CplFieldworkUpcoming[] = [
  { key: "fu-1", type: "Cluster Training", title: "Leadership Best Practice",      cluster: "Kitgum Central", date: "May 14, 2025", weekLabel: "Week 3" },
  { key: "fu-2", type: "School Visit",     title: "St. Mary's PS",                  cluster: "Pakele",         date: "May 15, 2025", weekLabel: "Week 3" },
  { key: "fu-3", type: "SSA",              title: "Kibale Central PS — SSA refresh", cluster: "Kampala",      date: "May 17, 2025", weekLabel: "Week 3" },
  { key: "fu-4", type: "Follow-Up Visit",  title: "Rwenzaba PS — improvement plan",  cluster: "Mbarara",      date: "May 19, 2025", weekLabel: "Week 4" },
];

export const cplFieldworkSummary = {
  monthLabel: "May 2025",
  visitsConducted: 14,
  visitsTarget: 18,
  trainingsDelivered: 6,
  trainingsTarget: 8,
  ssasConducted: 9,
  ssasTarget: 12,
  schoolsTouched: 11,         // distinct schools I personally engaged
  daysInField: 9,             // days out of 22 working days
  overallPct: 76,             // weighted personal achievement
};

// ────────── CCEO Performance (table) ──────────

export type RouteQuality = "Good" | "Average" | "Poor";
export type CceoRiskStatus = "Low" | "Medium" | "High";

export type CceoPerformanceRow = {
  id: string;
  name: string;
  initials: string;
  region: string;
  schoolsAssigned: number;
  plannedActivities: number;
  verifiedActivities: string; // "612 (75%)" — verified count + verified % within planned
  salesforcePending: number;
  backlog: number;
  routeQuality: RouteQuality;
  riskStatus: CceoRiskStatus;
};

export const cceoPerformance: CceoPerformanceRow[] = [
  { id: "cceo-1", name: "Grace Nansubuga", initials: "GN", region: "Central",   schoolsAssigned: 48, plannedActivities: 812, verifiedActivities: "612 (75%)", salesforcePending: 12, backlog: 9,  routeQuality: "Good",    riskStatus: "Low"    },
  { id: "cceo-2", name: "James Okello",    initials: "JO", region: "East",    schoolsAssigned: 52, plannedActivities: 890, verifiedActivities: "703 (79%)", salesforcePending: 8,  backlog: 14, routeQuality: "Good",    riskStatus: "Low"    },
  { id: "cceo-3", name: "Peter Ochieng",   initials: "PO", region: "North",   schoolsAssigned: 44, plannedActivities: 736, verifiedActivities: "485 (66%)", salesforcePending: 27, backlog: 22, routeQuality: "Average", riskStatus: "Medium" },
  { id: "cceo-4", name: "Sarah Namutebi",  initials: "SN", region: "West",    schoolsAssigned: 44, plannedActivities: 701, verifiedActivities: "512 (73%)", salesforcePending: 19, backlog: 11, routeQuality: "Good",    riskStatus: "Low"    },
  { id: "cceo-5", name: "David Tumusiime", initials: "DT", region: "North",   schoolsAssigned: 41, plannedActivities: 650, verifiedActivities: "396 (61%)", salesforcePending: 34, backlog: 25, routeQuality: "Poor",    riskStatus: "High"   },
];

// ────────── Approval Queue (plans only — never funds) ──────────

export type PlanIssue = "Missing Fields" | "Attachments Missing" | "Targets Not Set";

export type ApprovalQueueRow = {
  id: string;
  staff: string;
  initials: string;
  activitiesCovered: string; // "42 Activities"
  issues: PlanIssue[];
  submitted: string;
  primary: "Review" | "Approve";
};

export const approvalQueue: ApprovalQueueRow[] = [
  { id: "ap-1", staff: "Esther Adong",   initials: "EA", activitiesCovered: "42 Activities", issues: ["Missing Fields"],         submitted: "May 15", primary: "Review"  },
  { id: "ap-2", staff: "Joseph Kato",    initials: "JK", activitiesCovered: "38 Activities", issues: ["Missing Fields"],         submitted: "May 15", primary: "Approve" },
  { id: "ap-3", staff: "Mercy Auma",     initials: "MA", activitiesCovered: "27 Activities", issues: ["Attachments Missing"],    submitted: "May 14", primary: "Approve" },
  { id: "ap-4", staff: "Robert Ndawula", initials: "RN", activitiesCovered: "31 Activities", issues: ["Missing Fields"],         submitted: "May 14", primary: "Review"  },
  { id: "ap-5", staff: "Doreen Akello",  initials: "DA", activitiesCovered: "24 Activities", issues: ["Targets Not Set"],        submitted: "May 13", primary: "Review"  },
];

// ────────── Team Targets & Backlog Snapshot (6 mini tiles) ──────────

export type BacklogSnapshotTile = {
  key: string;
  label: string;
  value: string;
  delta: string;
  deltaTone: "up" | "down";
  icon: "users" | "database" | "wallet" | "schoolX" | "graduationCap" | "alertOctagon";
  tone: "amber" | "red" | "blue" | "violet" | "rose" | "lavender";
};

export const teamBacklogSnapshot: BacklogSnapshotTile[] = [
  { key: "below_target",   label: "Teams Below Target",            value: "14",  delta: "3 vs Apr",  deltaTone: "up", icon: "users",         tone: "amber"    },
  { key: "sf_overdue",     label: "Overdue Salesforce IDs",        value: "164", delta: "18 vs Apr", deltaTone: "up", icon: "database",      tone: "red"      },
  { key: "fnc",            label: "Funded Not Completed",          value: "86",  delta: "12 vs Apr", deltaTone: "up", icon: "wallet",        tone: "rose"     },
  { key: "no_visit",       label: "Schools with No Visit",         value: "128", delta: "11 vs Apr", deltaTone: "up", icon: "schoolX",       tone: "violet"   },
  { key: "no_training",    label: "Schools with No Training",      value: "97",  delta: "9 vs Apr",  deltaTone: "up", icon: "graduationCap", tone: "blue"     },
  { key: "neither",        label: "Schools w/ Neither Training Nor Visit", value: "35", delta: "4 vs Apr",  deltaTone: "up", icon: "alertOctagon",  tone: "lavender" },
];

// ────────── School & SSA Intelligence ──────────
//
// 8 SSA intervention areas (per product doc):
//   • Christ-like Behavior
//   • Exposure to the Word of God
//   • Fees / Budget / Accounts
//   • Government Requirements
//   • Leadership Best Practice
//   • Learning Environment
//   • Teaching Environment
//   • Enrollment
// The screenshot abbreviates labels to fit; the underlying mapping is preserved.

export type CplSsaKey =
  | "Visit"      // proxy for engagement: Christ-like Behavior visit cadence
  | "Training"   // teacher training (Teaching Environment)
  | "Mentoring"  // Leadership Best Practice mentoring frequency
  | "SBA"        // School-Based Assessment (Learning Environment)
  | "Govt"       // Government Requirements
  | "Linkage";   // Fees / Budget / Accounts + parent linkage

export const ssaClusterColumnMap: Record<CplSsaKey, { short: string; full: string }> = {
  Visit:    { short: "Visit",    full: "Christ-like Behavior · Visit cadence" },
  Training: { short: "Training", full: "Teaching Environment · Teacher training" },
  Mentoring:{ short: "Mentoring", full: "Leadership Best Practice · Mentoring" },
  SBA:      { short: "SBA",      full: "Learning Environment · School-Based Assessment" },
  Govt:     { short: "Govt", full: "Government Requirements" },
  Linkage:  { short: "Linkage",  full: "Fees / Budget / Accounts · Parent Linkage" },
};

export const ssaClusterColumnOrder: CplSsaKey[] = ["Visit", "Training", "Mentoring", "SBA", "Govt", "Linkage"];

export type SsaClusterRow = {
  cluster: string;
  scores: Record<CplSsaKey, number>;
  overall: number;
};

export const ssaClusterPerformance: SsaClusterRow[] = [
  { cluster: "Kampala", scores: { Visit: 92, Training: 88, Mentoring: 74, SBA: 78, Govt: 85, Linkage: 65 }, overall: 83 },
  { cluster: "Mukono",  scores: { Visit: 76, Training: 71, Mentoring: 63, SBA: 65, Govt: 72, Linkage: 56 }, overall: 70 },
  { cluster: "Mbarara", scores: { Visit: 64, Training: 58, Mentoring: 52, SBA: 56, Govt: 60, Linkage: 50 }, overall: 56 },
  { cluster: "Arua",    scores: { Visit: 48, Training: 44, Mentoring: 38, SBA: 32, Govt: 46, Linkage: 39 }, overall: 42 },
];

// ────────── Schools Needing Urgent Attention (compact) ──────────
//
// Priority ranking, per product doc:
//   1. SSA performance (lowest first) — primary driver
//   2. Becoming inactive / inactive
//   3. No visit
//   4. No training
//   5. Neither visit nor training

export type UrgentIssue = "No Visit, No Training" | "No Visit" | "No Training";

export type UrgentSchoolRow = {
  id: string;
  school: string;
  district: string;
  ssaScore: number;
  issue: UrgentIssue;
  risk: "High" | "Medium";
};

export const urgentSchools: UrgentSchoolRow[] = [
  { id: "us-1", school: "St. Mary's PS",     district: "Mukono",  ssaScore: 38, issue: "No Visit, No Training", risk: "High"   },
  { id: "us-2", school: "Kibale Central PS", district: "Kampala", ssaScore: 41, issue: "No Visit",              risk: "High"   },
  { id: "us-3", school: "Rwenzaba PS",       district: "Mbarara", ssaScore: 46, issue: "No Visit",              risk: "Medium" },
  { id: "us-4", school: "Kanyebwa PS",       district: "Arua",    ssaScore: 44, issue: "No Training",           risk: "Medium" },
  { id: "us-5", school: "Panyimur PS",       district: "Nebbi",   ssaScore: 39, issue: "No Visit, No Training", risk: "High"   },
];

// ────────── Smart Route & Capacity ──────────
// Smart route planner is GUIDANCE — not control. CCEOs may accept, ignore, or
// adjust suggestions. Tone here must remain encouraging, not punitive.

export type RouteCapacityKpi = {
  key: string;
  label: string;
  value: string;
  caption?: string;
  icon: "route" | "users" | "calendar" | "gauge";
  tone: "edify" | "amber" | "rose" | "blue";
};

export const routeCapacityKpis: RouteCapacityKpi[] = [
  { key: "rq",     label: "Route Quality (Teams)", value: "72%",  caption: "Good",       icon: "route",    tone: "edify" },
  { key: "ovr",    label: "Overloaded Staff",      value: "14",   caption: ">120% Capacity",  icon: "users",    tone: "amber" },
  { key: "leave",  label: "Leave Conflicts",       value: "8",    caption: "This Week",  icon: "calendar", tone: "rose"  },
  { key: "te",     label: "Travel Efficiency",     value: "68%",  caption: "vs Plan",    icon: "gauge",    tone: "blue"  },
];

export type RouteCceoRow = {
  cceo: string;
  routeQuality: RouteQuality;
  onTimeVisitsPct: number;
  avgTravelTime: string;
  efficiencyPct: number;
};

export const routeCceoTable: RouteCceoRow[] = [
  { cceo: "Grace Nansubuga", routeQuality: "Good",    onTimeVisitsPct: 92, avgTravelTime: "2.6 hrs", efficiencyPct: 75 },
  { cceo: "James Okello",    routeQuality: "Good",    onTimeVisitsPct: 88, avgTravelTime: "2.9 hrs", efficiencyPct: 72 },
  { cceo: "Peter Ochieng",   routeQuality: "Average", onTimeVisitsPct: 74, avgTravelTime: "3.4 hrs", efficiencyPct: 64 },
  { cceo: "Sarah Namutebi",  routeQuality: "Good",    onTimeVisitsPct: 85, avgTravelTime: "2.8 hrs", efficiencyPct: 70 },
  { cceo: "David Tumusiime", routeQuality: "Poor",    onTimeVisitsPct: 61, avgTravelTime: "4.1 hrs", efficiencyPct: 52 },
];

// ────────── Funding & Execution ──────────
// Program Lead has VISIBILITY here, not approval power.
// Final fund approval flow (per product doc): Accountant → Country Director → RVP.

export const fundUtilization = {
  pct: 68,
  utilizedLabel: "UGX 8.42B / 12.40B",
  trend: "6 pp vs Apr",
};

export type FundStatusRow = {
  key: string;
  label: string;
  count: number;
  amountLabel: string;
  tone: "amber" | "green" | "blue" | "red";
};

export const fundRequestStatus: FundStatusRow[] = [
  { key: "pending",  label: "Pending Approval",   count: 154, amountLabel: "UGX 2.78B", tone: "amber" },
  { key: "approved", label: "Approved",           count: 86,  amountLabel: "UGX 3.26B", tone: "blue"  },
  { key: "disbursed",label: "Disbursed",          count: 64,  amountLabel: "UGX 2.38B", tone: "green" },
  { key: "returned", label: "Returned / Rejected", count: 12, amountLabel: "UGX 0.32B", tone: "red"   },
];

// ────────── Quick Actions (6 cards) ──────────

export type CplQuickAction = {
  key: string;
  title: string;
  subtitle: string;
  icon: "clipboardList" | "layers" | "target" | "route" | "alertTriangle" | "calendar";
  href: string;
  tone: "edify" | "amber" | "violet" | "blue" | "red" | "green";
};

export const cplQuickActions: CplQuickAction[] = [
  { key: "review_approvals", title: "Review Approvals",      subtitle: "28 pending",            icon: "clipboardList", href: "#approvals",       tone: "edify"  },
  { key: "inspect_backlogs", title: "Inspect Backlogs",      subtitle: "164 items",             icon: "layers",        href: "#backlog-snapshot",tone: "amber"  },
  { key: "view_targets",     title: "View Team Targets",     subtitle: "Performance & gaps",    icon: "target",        href: "#team-performance",tone: "violet" },
  { key: "open_routes",      title: "Open Route Planner",    subtitle: "Plan & optimize",       icon: "route",         href: "#smart-route",     tone: "blue"   },
  { key: "review_at_risk",   title: "Review Schools at Risk",subtitle: "46 schools",            icon: "alertTriangle", href: "#urgent-schools",  tone: "red"    },
  { key: "open_planning",    title: "Open Monthly Planning", subtitle: "Build & submit plans",  icon: "calendar",      href: "/planning",        tone: "green"  },
];

// ────────── Identity & header ──────────

export const cplUser = {
  name: "Daniel Mwangi",
  initials: "DM",
  role: "Country Program Lead",
  online: true,
  scope: "Uganda",
};

export const cplHeader = {
  title: "Country Program Lead Dashboard",
  subtitle: "Team execution, approvals, targets, planning quality, and operational performance.",
  filters: {
    financialYear: "FY 2024/25",
    month: "May 2025",
    regionCountry: "Uganda",
  },
  searchPlaceholder: "Search schools, staff, regions…",
};

export const cplNotificationCount = 12;

// ──────────────────────────────────────────────────────────────────────────
// MOBILE — CPL phone shell
// ──────────────────────────────────────────────────────────────────────────
//
// The mobile experience is purpose-built for the lead-while-on-the-move use
// case: glance KPIs, approve plans, see who is behind. Keep the data "owned"
// by the lead's supervised team — never the entire country — so the donut /
// member list reads honestly to the person logged in.

// Hero copy on the dark home header
export const cplMobileHero = {
  greeting: "Country Program Lead",
  monthLabel: "May 2025",
  notificationCount: 3,
  title: "Lead with clarity.\nMove the team forward.",
  subtitle: "Every decision today builds stronger schools tomorrow.",
  monthlyAchievementPct: 78,
  monthlyAchievementLabel: "Overall Monthly Achievement",
};

// Six KPI tiles on the home screen (3-col grid, top of card list)
export type CplMobileKpi = {
  key: string;
  label: string;
  value: string;
  caption: string;
  captionTone: "edify" | "amber" | "rose";
  icon: "target" | "userTarget" | "clipboardList" | "userAlert" | "cloud" | "wallet";
  iconTone: "edify" | "amber" | "rose" | "blue";
};

export const cplMobileKpis: CplMobileKpi[] = [
  { key: "team_target",     label: "Team Target Progress",   value: "72%", caption: "On Track",     captionTone: "edify", icon: "target",        iconTone: "edify" },
  { key: "my_target",       label: "My Target Progress",     value: "68%", caption: "On Track",     captionTone: "edify", icon: "userTarget",    iconTone: "blue"  },
  { key: "plans_pending",   label: "Plans Awaiting Approval",value: "12",  caption: "Needs Action", captionTone: "amber", icon: "clipboardList", iconTone: "amber" },
  { key: "staff_at_risk",   label: "Staff at Risk",          value: "3",   caption: "Needs Support",captionTone: "rose",  icon: "userAlert",     iconTone: "rose"  },
  { key: "sf_pending",      label: "Salesforce IDs Pending", value: "8",   caption: "Pending",      captionTone: "edify", icon: "cloud",         iconTone: "edify" },
  { key: "fund_pending",    label: "Fund Requests Pending",  value: "5",   caption: "Pending",      captionTone: "edify", icon: "wallet",        iconTone: "edify" },
];

// "This Week" — 4 small tiles
export type CplWeekTile = {
  key: string;
  label: string;
  value: number;
  status: "Planned" | "Pendied" | "Due";
  icon: "graduationCap" | "schoolActivity" | "shieldCheck" | "checkCircle";
  tone: "edify" | "amber" | "violet" | "green";
};

export const cplWeekSummary = {
  cta: { label: "View Calendar", href: "/my-targets" },
  tiles: [
    { key: "cluster_trainings", label: "Cluster Trainings",  value: 6,  status: "Planned", icon: "graduationCap",  tone: "edify"  },
    { key: "in_school",         label: "In-School Activities", value: 18, status: "Planned", icon: "schoolActivity", tone: "amber"  },
    { key: "ssa_support",       label: "SSA Support",         value: 9,  status: "Pendied", icon: "shieldCheck",    tone: "violet" },
    { key: "follow_ups",        label: "Follow-Ups",          value: 14, status: "Due",     icon: "checkCircle",    tone: "green"  },
  ] as CplWeekTile[],
};

// "Team Trend" line chart — last 8 weeks of team achievement %
export const cplTeamTrend = [
  { week: "Mar 15",  pct: 64 },
  { week: "Mar 29",  pct: 71 },
  { week: "Apr 12",  pct: 53 },
  { week: "Apr 26",  pct: 76 },
  { week: "May 10",  pct: 73 },
  { week: "May 24",  pct: 78 },
];

// "Immediate Attention" — 3 quick alerts on the home screen
export type CplImmediateAttention = {
  key: string;
  label: string;
  href: string;
  tone: "amber" | "rose" | "edify";
  icon: "alertTriangle" | "fileWarning" | "route";
};

export const cplImmediateAttention: CplImmediateAttention[] = [
  { key: "behind_target",    label: "3 staff behind target",         href: "/my-team",      tone: "amber", icon: "alertTriangle" },
  { key: "awaiting_approval",label: "12 activities awaiting approval", href: "/approvals", tone: "rose",  icon: "fileWarning"   },
  { key: "overloaded_routes",label: "2 overloaded routes",           href: "/my-team",      tone: "edify", icon: "route"         },
];

// ── Team Performance screen ────────────────────────────────────────────

export type CplTeamRouteBadge = "Route A" | "Route B" | "Route C";
export type CplTeamRouteStatus = "Normal" | "High";
export type CplTeamMemberStatus = "On Track" | "At Risk" | "Behind";

export type CplTeamMember = {
  id: string;
  name: string;
  initials: string;
  role: "CCEO";
  achievementPct: number;
  status: CplTeamMemberStatus;
  backlog: number;
  routeBadge: CplTeamRouteBadge;
  routeStatus: CplTeamRouteStatus;
};

// Daniel Mwangi's directly supervised team (5 CCEOs).
// Aggregate counts shown in the donut (25 / 14 / 7 / 4) reflect the wider
// program — the person rows show only "my team."
export const cplMyTeam: CplTeamMember[] = [
  { id: "tm-1", name: "Sarah M.",  initials: "SM", role: "CCEO", achievementPct: 82, status: "On Track", backlog: 3,  routeBadge: "Route A", routeStatus: "Normal" },
  { id: "tm-2", name: "Peter K.",  initials: "PK", role: "CCEO", achievementPct: 65, status: "At Risk",  backlog: 7,  routeBadge: "Route B", routeStatus: "High"   },
  { id: "tm-3", name: "Moses T.",  initials: "MT", role: "CCEO", achievementPct: 48, status: "Behind",   backlog: 12, routeBadge: "Route C", routeStatus: "High"   },
  { id: "tm-4", name: "Joel O.",   initials: "JO", role: "CCEO", achievementPct: 74, status: "On Track", backlog: 2,  routeBadge: "Route A", routeStatus: "Normal" },
  { id: "tm-5", name: "Ruth W.",   initials: "RW", role: "CCEO", achievementPct: 91, status: "On Track", backlog: 1,  routeBadge: "Route B", routeStatus: "Normal" },
];

// Donut summary above the member list
export const cplTeamProgress = {
  monthLabel: "May 2025",
  donutPct: 72,
  totalCceos: 25,
  onTrack:  { count: 14, pct: 56 },
  atRisk:   { count: 7,  pct: 28 },
  behind:   { count: 4,  pct: 16 },
};

// "My Targets" footer panel on the team screen
export const cplMyTargetsSummary = {
  monthLabel: "May 2025",
  quarterly:  { pct: 64, status: "On Track" as const, icon: "target"   as const },
  monthly:    { pct: 68, status: "On Track" as const, icon: "calendar" as const },
  approvals:  { count: 38, label: "This Month",       icon: "checkCircle" as const },
};

// ── Approvals screen ───────────────────────────────────────────────────

export type CplApprovalCategory = "plans" | "funds" | "backlogs";
export type CplApprovalStatus =
  | "Awaiting Approval"
  | "Needs Review"
  | "Ready"
  | "Approved"
  | "Returned";

export type CplApprovalKind =
  | "cluster_training"
  | "school_visit"
  | "ssa_support"
  | "partner_followup";

export type CplApprovalItem = {
  id: string;
  category: CplApprovalCategory;
  kind: CplApprovalKind;
  title: string;
  owner: string;
  ownerRole: "CCEO" | "Coordinator";
  district: string;
  plannedRange: string;
  cost: string;          // "UGX 2,450" — pre-formatted
  status: CplApprovalStatus;
};

export const cplApprovalCounts = {
  waiting:        12,
  returned:       4,
  approvedToday:  8,
  criticalIssues: 2,
};

export const cplApprovalsList: CplApprovalItem[] = [
  { id: "ap-m-1", category: "plans",    kind: "cluster_training", title: "Cluster Training Batch 5", owner: "Sarah M.", ownerRole: "CCEO", district: "Northern District", plannedRange: "May 26 – 29", cost: "UGX 9.3M", status: "Awaiting Approval" },
  { id: "ap-m-2", category: "plans",    kind: "school_visit",     title: "School Visit – Week 21",   owner: "Peter K.", ownerRole: "CCEO", district: "Central District",  plannedRange: "May 25 – 29", cost: "UGX 4.5M", status: "Needs Review"      },
  { id: "ap-m-3", category: "plans",    kind: "ssa_support",      title: "SSA Support – Round 3",    owner: "Ruth W.",  ownerRole: "CCEO", district: "Eastern District",  plannedRange: "May 24 – 28", cost: "UGX 3.6M",   status: "Ready"             },
  { id: "ap-m-4", category: "plans",    kind: "partner_followup", title: "Partner Follow-Up Batch 2",owner: "Joel O.",  ownerRole: "CCEO", district: "Western District",  plannedRange: "May 26 – 30", cost: "UGX 3.0M",   status: "Awaiting Approval" },
  { id: "ap-m-5", category: "plans",    kind: "cluster_training", title: "Cluster Training Batch 6", owner: "Moses T.", ownerRole: "CCEO", district: "Northern District", plannedRange: "May 31 – Jun 3", cost: "UGX 9.9M", status: "Needs Review"      },
  { id: "ap-m-6", category: "funds",    kind: "cluster_training", title: "Training Materials Order", owner: "Sarah M.", ownerRole: "CCEO", district: "Northern District", plannedRange: "Disburse by May 30", cost: "UGX 5.4M", status: "Awaiting Approval" },
  { id: "ap-m-7", category: "funds",    kind: "school_visit",     title: "Field Travel – Week 22",   owner: "Peter K.", ownerRole: "CCEO", district: "Central District",  plannedRange: "Disburse by Jun 2",  cost: "UGX 2.4M",   status: "Needs Review"      },
  { id: "ap-m-8", category: "backlogs", kind: "ssa_support",      title: "SSA Round 2 — Outstanding",owner: "Moses T.", ownerRole: "CCEO", district: "Northern District", plannedRange: "Overdue 9 days",      cost: "—",      status: "Returned"          },
  { id: "ap-m-9", category: "backlogs", kind: "school_visit",     title: "April Visits — Salesforce IDs missing", owner: "Joel O.", ownerRole: "CCEO", district: "Western District", plannedRange: "Overdue 6 days", cost: "—", status: "Needs Review" },
];

// ── Targets screen ─────────────────────────────────────────────────────

export type CplTargetRing = {
  key: string;
  label: string;
  pct: number;
  current: number;
  total: number;
  caption: string;
  icon: "users" | "clipboardList" | "userCheck" | "wallet";
};

export const cplTargetRings: CplTargetRing[] = [
  { key: "supervision", label: "Supervision Visits",     pct: 70, current: 42, total: 60, caption: "8 vs Apr",  icon: "users"         },
  { key: "approvals",   label: "Plan Approvals",          pct: 70, current: 28, total: 40, caption: "6 vs Apr",  icon: "clipboardList" },
  { key: "reviews",     label: "Team Reviews",            pct: 72, current: 36, total: 50, caption: "7 vs Apr",  icon: "userCheck"     },
  { key: "fund_review", label: "Fund Requests Reviewed",  pct: 67, current: 8,  total: 12, caption: "2 vs Apr",  icon: "wallet"        },
];

export type CplTargetTeam = {
  key: string;
  label: string;
  achievedPct: number;
  on: number;
  off: number;
  caption: string;
  trend: "up" | "down";
};

// "Team Targets" — compact rows on the targets screen
export const cplTargetTeamRows: CplTargetTeam[] = [
  { key: "schools_visited",     label: "Schools Visited",          achievedPct: 78, on: 374, off: 106, caption: "vs target 480", trend: "up"   },
  { key: "trainings_delivered", label: "Trainings Delivered",      achievedPct: 65, on: 91,  off: 49,  caption: "vs target 140", trend: "up"   },
  { key: "ssa_completed",       label: "SSA Visits Completed",     achievedPct: 71, on: 122, off: 50,  caption: "vs target 172", trend: "down" },
  { key: "follow_ups",          label: "Follow-ups Closed",        achievedPct: 82, on: 64,  off: 14,  caption: "vs target 78",  trend: "up"   },
];

// ── Per-team target breakdown ──────────────────────────────────────────
// For each team-level target, show how each *supervised* CCEO contributes.
// Member IDs match cplMyTeam so the same identity flows through screens.

export type CplMemberContribution = {
  memberId: string;       // matches CplTeamMember.id
  name: string;
  initials: string;
  achieved: number;
  target: number;
  pct: number;
  status: "On Track" | "At Risk" | "Behind"; // mirrors team-level status
};

export type CplTeamTargetBreakdown = {
  key: string;
  label: string;
  unit: string;            // "schools" / "trainings" / "visits" / etc
  totalAchieved: number;
  totalTarget: number;
  achievedPct: number;
  trend: "up" | "down";
  trendDelta: string;      // "6 pp vs Apr"
  topContributorId: string; // member id with highest pct
  laggingMemberId: string;  // member id with lowest pct
  members: CplMemberContribution[];
};

export const cplTeamTargetBreakdown: CplTeamTargetBreakdown[] = [
  {
    key: "schools_visited",
    label: "Schools Visited",
    unit: "schools",
    totalAchieved: 374,
    totalTarget: 480,
    achievedPct: 78,
    trend: "up",
    trendDelta: "6 pp vs Apr",
    topContributorId: "tm-5",
    laggingMemberId:  "tm-3",
    members: [
      { memberId: "tm-1", name: "Sarah M.", initials: "SM", achieved: 86, target: 96,  pct: 90, status: "On Track" },
      { memberId: "tm-2", name: "Peter K.", initials: "PK", achieved: 62, target: 96,  pct: 65, status: "At Risk"  },
      { memberId: "tm-3", name: "Moses T.", initials: "MT", achieved: 44, target: 96,  pct: 46, status: "Behind"   },
      { memberId: "tm-4", name: "Joel O.",  initials: "JO", achieved: 80, target: 96,  pct: 83, status: "On Track" },
      { memberId: "tm-5", name: "Ruth W.",  initials: "RW", achieved: 102, target: 96, pct: 106, status: "On Track" },
    ],
  },
  {
    key: "trainings_delivered",
    label: "Trainings Delivered",
    unit: "trainings",
    totalAchieved: 91,
    totalTarget: 140,
    achievedPct: 65,
    trend: "up",
    trendDelta: "4 pp vs Apr",
    topContributorId: "tm-1",
    laggingMemberId:  "tm-3",
    members: [
      { memberId: "tm-1", name: "Sarah M.", initials: "SM", achieved: 26, target: 28, pct: 93, status: "On Track" },
      { memberId: "tm-2", name: "Peter K.", initials: "PK", achieved: 16, target: 28, pct: 57, status: "At Risk"  },
      { memberId: "tm-3", name: "Moses T.", initials: "MT", achieved:  9, target: 28, pct: 32, status: "Behind"   },
      { memberId: "tm-4", name: "Joel O.",  initials: "JO", achieved: 19, target: 28, pct: 68, status: "On Track" },
      { memberId: "tm-5", name: "Ruth W.",  initials: "RW", achieved: 21, target: 28, pct: 75, status: "On Track" },
    ],
  },
  {
    key: "ssa_completed",
    label: "SSA Visits Completed",
    unit: "visits",
    totalAchieved: 122,
    totalTarget: 172,
    achievedPct: 71,
    trend: "down",
    trendDelta: "3 pp vs Apr",
    topContributorId: "tm-5",
    laggingMemberId:  "tm-3",
    members: [
      { memberId: "tm-1", name: "Sarah M.", initials: "SM", achieved: 30, target: 35, pct: 86, status: "On Track" },
      { memberId: "tm-2", name: "Peter K.", initials: "PK", achieved: 22, target: 35, pct: 63, status: "At Risk"  },
      { memberId: "tm-3", name: "Moses T.", initials: "MT", achieved: 14, target: 34, pct: 41, status: "Behind"   },
      { memberId: "tm-4", name: "Joel O.",  initials: "JO", achieved: 24, target: 34, pct: 71, status: "On Track" },
      { memberId: "tm-5", name: "Ruth W.",  initials: "RW", achieved: 32, target: 34, pct: 94, status: "On Track" },
    ],
  },
  {
    key: "follow_ups",
    label: "Follow-ups Closed",
    unit: "follow-ups",
    totalAchieved: 64,
    totalTarget: 78,
    achievedPct: 82,
    trend: "up",
    trendDelta: "5 pp vs Apr",
    topContributorId: "tm-5",
    laggingMemberId:  "tm-3",
    members: [
      { memberId: "tm-1", name: "Sarah M.", initials: "SM", achieved: 14, target: 16, pct: 88, status: "On Track" },
      { memberId: "tm-2", name: "Peter K.", initials: "PK", achieved: 11, target: 16, pct: 69, status: "At Risk"  },
      { memberId: "tm-3", name: "Moses T.", initials: "MT", achieved:  6, target: 16, pct: 38, status: "Behind"   },
      { memberId: "tm-4", name: "Joel O.",  initials: "JO", achieved: 14, target: 15, pct: 93, status: "On Track" },
      { memberId: "tm-5", name: "Ruth W.",  initials: "RW", achieved: 19, target: 15, pct: 127, status: "On Track" },
    ],
  },
];

// ─────────── Dual command lanes ───────────
// PLs are player-coaches: they deliver field work AND manage CCEOs. The
// command strip splits into two lanes so the PL sees both jobs at once —
// "what I must deliver myself" vs "what my team needs from me".
export type PlLaneItem = {
  label: string;
  href: string;
  /** Optional urgency accent for the leading dot. */
  tone?: "edify" | "amber" | "rose";
};

// My Field Work — the PL's own implementation target.
export const cplFieldLane: PlLaneItem[] = [
  { label: "Schedule 2 PL school visits this month", href: "/planning" },
  { label: "Enter TS ID for 1 completed training", href: "/data-verification", tone: "amber" },
  { label: "File today's program debrief", href: "/debriefs/new" },
];

// My Team Work — what the CCEO team needs the PL to act on.
export const cplTeamLane: PlLaneItem[] = [
  { label: "4 CCEOs have unplanned schools", href: "/my-team", tone: "amber" },
  { label: "3 partner activities need PL approval", href: "/approvals", tone: "amber" },
  { label: "2 monthly fund requests to review", href: "/fund-requests" },
];
