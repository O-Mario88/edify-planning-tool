// CCEO Dashboard — desktop / tablet mock data layer.
//
// Backs the "Overview of Core School performance and progress" view.
// Numbers are illustrative; shapes match what the real backend will return
// so every card swaps to db.* without UI changes.

// ────────── Identity & header ──────────

export const cceoUser = {
  name: "Sarah Okello",
  initials: "SO",
  role: "CCEO",
  cluster: "Kigun District",
  org: "UCI · Impacting Lives, Transforming Nations",
  quote: "Leadership is service in action.",
  quoteAttribution: "Unknown",
};

export const cceoDashboardHeader = {
  title: "CCEO Dashboard",
  subtitle: "Overview of Core School performance and progress",
  filters: {
    month:            "May 2025",
    compare:          "Compare: Apr 2025",
    district:         "Kigun District",
    districtCaption:  "All Clusters",
  },
  notificationsCount: 12,
  needsAttentionCount: 18,
};

// Top-right profile chip — mirrors the user shown in the sidebar so
// they don't drift. Pull from `cceoUser` for the live wiring later.
export const cceoHeaderProfile = {
  name:      "Sarah Okello",
  initials:  "SO",
  role:      "CCEO",
  online:    true,
  avatarUrl: null as string | null,
};

// ────────── KPI row (6 cards) ──────────

export type CceoKpi = {
  key: string;
  label: string;
  value: string;
  subValue?: string;          // "(95%)" — appears next to the main number
  trendDelta: string;         // "6", "4%", "0.3"
  trendTone: "up" | "down";
  trendSuffix: string;        // "vs Apr 2025"
  visual:
    | { kind: "icon";  icon: "school" | "checkCircle" | "trendingUp" }
    | { kind: "ring";  pct: number; color: "edify" | "green" | "amber" | "rose" };
};

export const cceoKpis: CceoKpi[] = [
  { key: "total_core",      label: "Total Core Schools",  value: "128",                        trendDelta: "6",   trendTone: "up",   trendSuffix: "vs Apr 2025", visual: { kind: "icon", icon: "school"      } },
  { key: "schools_assessed",label: "Schools Assessed",     value: "122", subValue: "(95%)",     trendDelta: "4%",  trendTone: "up",   trendSuffix: "vs Apr 2025", visual: { kind: "icon", icon: "checkCircle" } },
  { key: "avg_ssa",         label: "Avg SSA Score",        value: "7.6", subValue: "/10",       trendDelta: "0.3", trendTone: "up",   trendSuffix: "vs Apr 2025", visual: { kind: "icon", icon: "trendingUp"  } },
  { key: "on_track",        label: "On Track",             value: "89",  subValue: "(70%)",     trendDelta: "5%",  trendTone: "up",   trendSuffix: "vs Apr 2025", visual: { kind: "ring", pct: 70, color: "green" } },
  { key: "behind",          label: "Behind Schedule",      value: "27",  subValue: "(21%)",     trendDelta: "3%",  trendTone: "down", trendSuffix: "vs Apr 2025", visual: { kind: "ring", pct: 21, color: "amber" } },
  { key: "critical",        label: "Critical Gap",         value: "12",  subValue: "(9%)",      trendDelta: "2%",  trendTone: "down", trendSuffix: "vs Apr 2025", visual: { kind: "ring", pct: 9,  color: "rose"  } },
];

// ────────── Core Service Package Progress (8 tiles + summary) ──────────

export type CceoServicePackageTile = {
  key: string;
  label: string;          // "0 SSA", "1V + 1T", "Potential Champion"
  count: number;          // 6, 8, 31, 14, …
  pctOfTotal: number;     // 5, 6, 24, 11, …
  icon: "doc" | "calendar" | "users" | "school1v1t" | "school2v2t" | "school3v3t" | "schoolCheck" | "trophy";
  tone: "slate" | "rose" | "amber" | "blue" | "violet" | "indigo" | "green" | "yellow";
};

export const corePackageTiles: CceoServicePackageTile[] = [
  { key: "0ssa",  label: "0 SSA",      count: 6,  pctOfTotal: 5,  icon: "doc",         tone: "slate"  },
  { key: "0v",    label: "0 Visits",   count: 8,  pctOfTotal: 6,  icon: "calendar",    tone: "rose"   },
  { key: "0t",    label: "0 Training", count: 7,  pctOfTotal: 5,  icon: "users",       tone: "amber"  },
  { key: "1v1t",  label: "1V + 1T",    count: 18, pctOfTotal: 14, icon: "school1v1t",  tone: "blue"   },
  { key: "2v2t",  label: "2V + 2T",    count: 26, pctOfTotal: 20, icon: "school2v2t",  tone: "violet" },
  { key: "3v3t",  label: "3V + 3T",    count: 24, pctOfTotal: 19, icon: "school3v3t",  tone: "indigo" },
  { key: "4v4t",  label: "4V + 4T",    count: 31, pctOfTotal: 24, icon: "schoolCheck", tone: "green"  },
  { key: "champ", label: "Potential Champion", count: 14, pctOfTotal: 11, icon: "trophy", tone: "yellow" },
];

export const minimumCoreSupport = {
  title: "Minimum Core Support Started",
  subtitle: "(At least 1 Visit + 1 Training)",
  pct: 79,
};

export const remainingPackageTasks = [
  { key: "visits_2plus",      label: "62 schools need 2+ more visits",   icon: "calendar"     as const, tone: "blue"  as const },
  { key: "training_1plus",    label: "46 schools need 1+ more training", icon: "graduationCap" as const, tone: "amber" as const },
  { key: "final_verification",label: "21 schools need final verification", icon: "shieldCheck" as const, tone: "green" as const },
];

// ────────── Core SSA Average Trend (line chart) ──────────

export type CceoSsaTrendPoint = { month: string; score: number };

export const coreSsaTrend: CceoSsaTrendPoint[] = [
  { month: "Dec",  score: 6.7 },
  { month: "Jan",  score: 7.0 },
  { month: "Feb",  score: 6.8 },
  { month: "Mar",  score: 7.2 },
  { month: "Apr",  score: 7.3 },
  { month: "May",  score: 7.6 },
];

export const coreSsaTrendHighlight = {
  monthLabel: "May 2025",
  score: 7.6,
  delta: "0.3",
  deltaTone: "up" as const,
  compareLabel: "vs Apr",
};

// ────────── SSA Performance by Intervention (8 horizontal bars) ──────────
//
// Order: descending performance (Christ-like Behavior at top).
// Tone is calculated from the score: ≥7.5 green, 6.5–7.4 amber, <6.5 rose.

export type CceoInterventionRow = {
  key: string;
  label: string;
  icon: "heart" | "book" | "shield" | "graduationCap" | "schoolBook" | "scale" | "wallet" | "users";
  score: number;          // 0–10
};

export const ssaInterventionRows: CceoInterventionRow[] = [
  { key: "christlike",   label: "Christ-like Behavior",        icon: "heart",         score: 8.3 },
  { key: "exposure",     label: "Exposure to the Word of God", icon: "book",          score: 8.1 },
  { key: "leadership",   label: "Leadership Best Practice",    icon: "shield",        score: 7.8 },
  { key: "teaching",     label: "Teaching Environment",        icon: "graduationCap", score: 7.6 },
  { key: "learning",     label: "Learning Environment",        icon: "schoolBook",    score: 7.4 },
  { key: "government",   label: "Government Requirements",     icon: "scale",         score: 7.1 },
  { key: "fees",         label: "Fees / Budget / Accounts",    icon: "wallet",        score: 6.6 },
  { key: "enrollment",   label: "Enrollment",                  icon: "users",         score: 6.2 },
];

// ────────── Core SSA Heatmap (district × intervention) ──────────

export type CceoHeatmapRow = {
  district: string;
  scores: {
    christlike: number;
    word: number;
    leadership: number;
    teaching: number;
    enrollment: number;
  };
  avg: number;
};

export const cceoHeatmap: CceoHeatmapRow[] = [
  { district: "Chongwe",       scores: { christlike: 8.4, word: 8.2, leadership: 8.0, teaching: 7.6, enrollment: 7.2 }, avg: 7.9 },
  { district: "Lusaka",        scores: { christlike: 8.1, word: 7.9, leadership: 7.6, teaching: 7.3, enrollment: 6.9 }, avg: 7.6 },
  { district: "Kabwe",         scores: { christlike: 7.8, word: 7.5, leadership: 7.2, teaching: 6.9, enrollment: 6.4 }, avg: 7.2 },
  { district: "Kitwe",         scores: { christlike: 7.6, word: 7.3, leadership: 7.0, teaching: 6.7, enrollment: 6.2 }, avg: 6.9 },
  { district: "Ndola",         scores: { christlike: 7.4, word: 7.1, leadership: 6.8, teaching: 6.5, enrollment: 5.9 }, avg: 6.7 },
  { district: "Mufulira",      scores: { christlike: 7.1, word: 6.8, leadership: 6.5, teaching: 6.1, enrollment: 5.6 }, avg: 6.4 },
  { district: "Chillalombwe",  scores: { christlike: 6.8, word: 6.4, leadership: 6.0, teaching: 5.8, enrollment: 5.3 }, avg: 6.1 },
];

// ────────── Best Performing Core Schools ──────────

export type CceoBestSchool = {
  rank: number;
  schoolName: string;
  district: string;
  ssaAvg: number;
  improvement: number;        // 1.4 means ↑ 1.4 vs last year
  visits: string;             // "4/4"
  trainings: string;          // "4/4"
  status: "Complete" | "Nearly Complete";
  recommendation: "Champion Review" | "Potential Champion";
};

export const bestPerformingCoreSchools: CceoBestSchool[] = [
  { rank: 1, schoolName: "Chongwe Christian School", district: "Chongwe", ssaAvg: 9.1, improvement: 1.4, visits: "4/4", trainings: "4/4", status: "Complete",        recommendation: "Champion Review"   },
  { rank: 2, schoolName: "Living Word Academy",      district: "Lusaka",  ssaAvg: 8.9, improvement: 1.1, visits: "4/4", trainings: "4/4", status: "Complete",        recommendation: "Potential Champion" },
  { rank: 3, schoolName: "Hope International School",district: "Kabwe",   ssaAvg: 8.7, improvement: 1.3, visits: "4/4", trainings: "4/4", status: "Complete",        recommendation: "Potential Champion" },
  { rank: 4, schoolName: "Grace Community School",   district: "Kitwe",   ssaAvg: 8.4, improvement: 0.9, visits: "3/4", trainings: "4/4", status: "Nearly Complete", recommendation: "Potential Champion" },
  { rank: 5, schoolName: "Victory Academy",          district: "Ndola",   ssaAvg: 8.2, improvement: 0.6, visits: "4/4", trainings: "3/4", status: "Nearly Complete", recommendation: "Potential Champion" },
];

// ────────── Core Schools Needing Attention ──────────

export type CceoAttentionSchool = {
  schoolName: string;
  district: string;
  ssaAvg: number;
  lowestIntervention: string;
  visits: string;
  trainings: string;
  riskLabel: string;
  riskTone: "rose" | "amber" | "violet";
};

export const coreSchoolsNeedingAttention: CceoAttentionSchool[] = [
  { schoolName: "New Dawn School",       district: "Mufulira",     ssaAvg: 4.8, lowestIntervention: "Enrollment",         visits: "0/4", trainings: "0/4", riskLabel: "No SSA, No Visits, No Trainings", riskTone: "rose"   },
  { schoolName: "Bright Future School",  district: "Chillalombwe", ssaAvg: 5.1, lowestIntervention: "Fees/Budget",        visits: "1/4", trainings: "1/4", riskLabel: "Low SSA, Behind Schedule",         riskTone: "amber"  },
  { schoolName: "Unity Christian School",district: "Kabwe",        ssaAvg: 5.3, lowestIntervention: "Teaching Env.",      visits: "1/4", trainings: "0/4", riskLabel: "No Training, Behind Schedule",     riskTone: "violet" },
  { schoolName: "Cornerstone School",    district: "Kitwe",        ssaAvg: 5.6, lowestIntervention: "Govt. Req.",         visits: "1/4", trainings: "1/4", riskLabel: "Low SSA, Behind Schedule",         riskTone: "amber"  },
  { schoolName: "Redeemer School",       district: "Chongwe",      ssaAvg: 5.7, lowestIntervention: "Enrollment",         visits: "0/4", trainings: "1/4", riskLabel: "No Visits, Behind Schedule",       riskTone: "rose"   },
];

// ────────── Champion School Pipeline (donut + legend + footer) ──────────

export const championPipeline = {
  total: 14,
  totalLabel: "Schools",
  segments: [
    { key: "review",    label: "Champion Review",   count: 4, pct: 29, color: "#10b981" },
    { key: "potential", label: "Potential Champion", count: 8, pct: 57, color: "#22c55e" },
    { key: "ineligible", label: "Not Eligible",      count: 2, pct: 14, color: "#cbd5e1" },
  ],
  footerNote:
    "Keep up the momentum! 14 schools are in the Champion pipeline. Your leadership is raising the standard of Christ-centered education.",
};

// ────────── Hero ("What Changed") + Quick Actions ──────────
//
// Computed values are pre-shaped here so the hero renders deterministically
// for the demo. In production these would be derived from the same engine
// that feeds the KPI row / SSA cards / champion pipeline so the chip
// numbers stay in lock-step with the rest of the page.

export const cceoHero = {
  greeting: "Good morning",
  firstName: cceoUser.name.split(" ")[0],
  totalCoreSchools: 128,
  ssaScore: 7.6,
  ssaDelta: 0.3,
  championReady: 4,
  criticalCount: 5,
  primaryCta:   { label: "Review This Week", href: "/planning" },
  secondaryCta: { label: "Open Route Plan",  href: "/route" },
};

export type CceoQuickAction = {
  key: string;
  title: string;
  count: number | string;
  caption: string;
  icon: "clipboardList" | "calendar" | "footprints" | "shieldCheck" | "trophy" | "fileText";
  href: string;
  tone: "edify" | "amber" | "violet" | "blue" | "red" | "green";
};

export const cceoQuickActions: CceoQuickAction[] = [
  { key: "plan_week",        title: "Plan This Week",     count: 12,     caption: "activities pending",  icon: "clipboardList", href: "/planning",            tone: "edify"  },
  { key: "schedule_visit",   title: "Schedule Visit",     count: 5,      caption: "schools below 6.0",   icon: "calendar",      href: "/schools",             tone: "red"    },
  { key: "log_visit",        title: "Log Visit Today",    count: 3,      caption: "scheduled today",     icon: "footprints",    href: "/trainings",           tone: "blue"   },
  { key: "open_ssa",         title: "Open SSA Form",      count: 6,      caption: "no SSA this FY",      icon: "shieldCheck",   href: "/ssa",                 tone: "amber"  },
  { key: "review_champions", title: "Review Champions",   count: 4,      caption: "ready for review",    icon: "trophy",        href: "/ssa/core-candidates", tone: "green"  },
  { key: "send_debrief",     title: "Send Daily Debrief", count: "Due",  caption: "today",               icon: "fileText",      href: "/field-intelligence",  tone: "violet" },
];

// ────────── Operating-view dashboard data ──────────
//
// Six-tile KPI row (Operating View). Each tile is a single number with a
// short trend pill and a 6-point sparkline so the read is fast.

export type CceoOperatingKpi = {
  key: string;
  label: string;
  value: string;
  unit?: string;
  delta: string;        // "+7", "+6%", "-8%", etc.
  deltaTone: "up" | "down";
  caption: string;      // "vs Apr"
  /** Donut ring on the right side of the tile (0–100). Omit for tiles
   *  that should render without a ring (the first two in the reference). */
  ringPct?: number;
  /** Ring tone — green for positive progress, amber for warning. */
  ringTone?: "emerald" | "amber" | "rose";
  icon: "school" | "users" | "shieldCheck" | "target" | "cloud" | "refresh";
  iconTone: "edify" | "emerald" | "violet" | "amber" | "rose" | "blue";
};

export const cceoOperatingKpis: CceoOperatingKpi[] = [
  { key: "tracked",   label: "Schools Tracked",         value: "128", delta: "+7",   deltaTone: "up",   caption: "vs Apr",                                 icon: "school",      iconTone: "edify"   },
  { key: "reached",   label: "Schools Reached",         value: "89",  delta: "+7",   deltaTone: "up",   caption: "vs Apr",                                 icon: "users",       iconTone: "emerald" },
  { key: "verified",  label: "Verified Visits",         value: "92",  unit: "%",    delta: "+6%",  deltaTone: "up",   caption: "vs Apr", ringPct: 92, ringTone: "emerald", icon: "shieldCheck", iconTone: "emerald" },
  { key: "target",    label: "Monthly Target Progress", value: "81",  unit: "%",    delta: "+9%",  deltaTone: "up",   caption: "vs Apr", ringPct: 81, ringTone: "emerald", icon: "target",      iconTone: "violet"  },
  { key: "salesforce",label: "Awaiting Salesforce ID",  value: "11",                delta: "-8%",  deltaTone: "down", caption: "vs Apr", ringPct: 35, ringTone: "amber",   icon: "cloud",       iconTone: "amber"   },
  { key: "returned",  label: "Returned Corrections",    value: "6",                 delta: "-25%", deltaTone: "down", caption: "vs Apr", ringPct: 75, ringTone: "emerald", icon: "refresh",     iconTone: "rose"    },
];

// Hero chips for the Operating View — derived headline numbers from the
// same dataset the KPIs and SSA cards show, so the chips never drift.

export const cceoOperatingHero = {
  greeting:  "Good morning",
  firstName: "Sarah",
  quote:     "Lead boldly. Serve deeply. Change lives.",
  subtext:   "Every school you reach becomes a community that thrives.",
  chips: [
    { key: "ssa",      tone: "good" as const, label: "+0.3 SSA",      caption: "vs Apr" },
    { key: "champion", tone: "info" as const, label: "4 Champion-ready", caption: "ready to promote" },
    { key: "critical", tone: "warn" as const, label: "5 Critical",    caption: "below 6.0" },
  ],
  primaryCta:   { label: "Review This Week", href: "/planning" },
  secondaryCta: { label: "Open Route Plan",  href: "/route" },
};

// Month planner — 5 columns (weeks) × 2 activity rows. Buffer days
// surface unscheduled capacity at the bottom of the card.

export type CceoMonthPlannerColumn = {
  weekLabel: string;        // "WEEK 1"
  rangeLabel: string;       // "Apr 28 — May 4"
  clusterTrainings: number; // 3
  inSchoolActivities: number;
};

export const cceoMonthPlanner = {
  month: "May 2025",
  columns: [
    { weekLabel: "WEEK 1", rangeLabel: "Apr 28 — May 4",  clusterTrainings: 3, inSchoolActivities: 16 },
    { weekLabel: "WEEK 2", rangeLabel: "May 5 — May 11",  clusterTrainings: 4, inSchoolActivities: 18 },
    { weekLabel: "WEEK 3", rangeLabel: "May 12 — May 18", clusterTrainings: 3, inSchoolActivities: 20 },
    { weekLabel: "WEEK 4", rangeLabel: "May 19 — May 25", clusterTrainings: 2, inSchoolActivities: 14 },
    { weekLabel: "WEEK 5", rangeLabel: "May 26 — May 31", clusterTrainings: 2, inSchoolActivities: 10 },
  ] as CceoMonthPlannerColumn[],
  totalDaysPlanned: "22/23",
  bufferDays: 1,
};

// Monthly activity breakdown — 7 activity types with counts and % of
// month total. Numbers sum to the dashboard's headline 132 activities.

export type CceoActivityBreakdownRow = {
  key: string;
  label: string;
  count: number;
  pct: number;        // % of total
  barColor: string;
};

export const cceoMonthlyActivityBreakdown = {
  totalActivities: 132,
  totalDelta: "+18% vs Apr",
  totalDeltaTone: "up" as const,
  rows: [
    { key: "cluster",     label: "Cluster Trainings",          count: 14, pct: 11, barColor: "#10b981" },
    { key: "school_me",   label: "School Visits by Me",        count: 42, pct: 32, barColor: "#3257d9" },
    { key: "follow_part", label: "Follow-Up Visits by Partner", count: 18, pct: 14, barColor: "#22c55e" },
    { key: "ssa",         label: "SSA Follow-Up",              count: 20, pct: 15, barColor: "#8b5cf6" },
    { key: "in_school",   label: "In-School Coaching",         count: 16, pct: 12, barColor: "#0ea5e9" },
    { key: "lessons",     label: "Lessons Observation",        count: 10, pct: 8,  barColor: "#f59e0b" },
    { key: "handover",    label: "Handover Meetings",          count: 12, pct: 9,  barColor: "#ef4444" },
  ] as CceoActivityBreakdownRow[],
};

// Salesforce Completion Queue — pending IDs the CCEO must confirm,
// review, or create. Match status drives the primary inline action.

export type CceoSfMatchStatus = "Smart Match" | "Possible Match" | "No Match" | "Submitted";

export type CceoSalesforceRow = {
  key: string;
  school: string;
  completedOn: string;  // "May 09"
  matchStatus: CceoSfMatchStatus;
};

export const cceoSalesforceQueue: CceoSalesforceRow[] = [
  { key: "sf-1", school: "Hope Primary School",     completedOn: "May 09", matchStatus: "Smart Match"    },
  { key: "sf-2", school: "St. Peter Primary",       completedOn: "May 08", matchStatus: "Smart Match"    },
  { key: "sf-3", school: "Grace Primary School",    completedOn: "May 07", matchStatus: "Possible Match" },
  { key: "sf-4", school: "Kigun Central Cluster",   completedOn: "May 06", matchStatus: "No Match"       },
  { key: "sf-5", school: "Bright Future PS",        completedOn: "May 05", matchStatus: "Smart Match"    },
];

// Monthly Route Opportunities — pre-computed bundles the planner can
// commit to. Each bundle aggregates a set of schools by geography.

export type CceoRouteImpact = "High Impact" | "Medium Impact" | "Low Impact";

export type CceoRouteBundle = {
  key: string;
  label: string;
  weekRange: string;     // "Wk 1-2"
  schools: number;
  impact: CceoRouteImpact;
  openCount: number;     // 8 Open
};

export const cceoRouteOpportunities: CceoRouteBundle[] = [
  { key: "rb-a", label: "Route Bundle A", weekRange: "Wk 1-2", schools: 12, impact: "High Impact",   openCount: 8 },
  { key: "rb-b", label: "Route Bundle B", weekRange: "Wk 3-3", schools: 10, impact: "Medium Impact", openCount: 6 },
  { key: "rb-c", label: "Route Bundle C", weekRange: "Wk 3-4", schools: 9,  impact: "High Impact",   openCount: 5 },
  { key: "rb-d", label: "Route Bundle D", weekRange: "Wk 4-5", schools: 7,  impact: "Medium Impact", openCount: 3 },
];

// Cluster Schedule — upcoming cluster days with readiness pills.

export type CceoClusterReadiness = "Ready" | "In Progress" | "Planned";

export type CceoClusterScheduleRow = {
  key: string;
  cluster: string;
  date: string;        // "May 06"
  district: string;
  readiness: CceoClusterReadiness;
};

export const cceoClusterSchedule: CceoClusterScheduleRow[] = [
  { key: "cs-1", cluster: "Kigun Central Cluster", date: "May 06", district: "Kigun", readiness: "Ready"       },
  { key: "cs-2", cluster: "Maryhill Cluster",      date: "May 10", district: "Kigun", readiness: "Ready"       },
  { key: "cs-3", cluster: "Kigun West Cluster",    date: "May 14", district: "Kigun", readiness: "In Progress" },
  { key: "cs-4", cluster: "Kigun East Cluster",    date: "May 20", district: "Kigun", readiness: "In Progress" },
  { key: "cs-5", cluster: "North Ridge Cluster",   date: "May 27", district: "Kigun", readiness: "Planned"     },
];

// Quick Context / Next Priority School — single school the CCEO is
// expected to focus on next, with contact, weakest intervention, and
// the recommended focus.

export const cceoNextPrioritySchool = {
  schoolName:       "Hope Primary School",
  cluster:          "Kigun Central Cluster",
  contactPerson:    { name: "Jane Achieng", role: "HT", phone: "+254 712 345 678" },
  weakestIntervention: "SSA Follow-Up",
  recommendedFocus: "Improve SSA engagement & feedback loops",
  lastVisit:        "May 02, 2025",
  nextPlannedVisit: "May 16, 2025",
};

// Momentum banner — closing celebration strip. The streak is tied to
// a real consistency metric (8 weeks at or above 90% completion) so
// it isn't gamification kitsch.

export const cceoMomentum = {
  headline:    "Great momentum, Sarah!",
  body:        "You are leading with excellence and creating real change. Keep inspiring schools and communities across Kigun District.",
  stats: [
    { key: "on_track", label: "On Track",      value: "On Track",  caption: "You're on track to hit your monthly targets" },
    { key: "quality",  label: "Quality Score", value: "92%",       caption: "Excellent",  showLive: true },
    { key: "streak",   label: "Consistency",   value: "8 Weeks",   caption: "Strong streak!" },
  ],
};

// ────────── CCEO sidebar (matches the dashboard screenshot) ──────────
//
// Items without a dedicated route deep-link to anchors on
// /dashboards/cceo (the CCEO dashboard route) so the sidebar feels
// alive without us having to spin up 10 placeholder pages.

export type CceoMenuSection = "My Work" | "Schools" | "Activity" | "Insights" | "Account";

export type CceoMenuItem = {
  label:   string;
  href:    string;
  icon:    string;
  badge?:  number;
  /** Grouping label rendered as a section header in the sidebar. Items
   *  with the same `section` are rendered together; ordering within a
   *  section follows array order below. Sectioning matches the rhythm
   *  of every other role's sidebar (My Work / Schools / Activity /
   *  Insights / Account) so a CCEO and a CPL recognise the layout. */
  section: CceoMenuSection;
};

export const cceoSidebarItems: CceoMenuItem[] = [
  // My Work — personal command surfaces
  { section: "My Work",  label: "Overview",           href: "/dashboards/cceo",               icon: "layoutDashboard" },
  { section: "My Work",  label: "Today's Tasks",      href: "/today",                         icon: "calendarCheck" },
  { section: "My Work",  label: "My Plan",            href: "/my-plan",                       icon: "clipboardList" },
  { section: "My Work",  label: "My Targets",         href: "/my-targets",                    icon: "target" },

  // Schools — the field of play
  { section: "Schools",  label: "My Portfolio",       href: "/portfolio",                     icon: "school" },
  { section: "Schools",  label: "Core Schools",       href: "/core-schools",                  icon: "school" },
  { section: "Schools",  label: "SSA Performance",    href: "/ssa",                           icon: "activity" },
  { section: "Schools",  label: "Visits & Trainings", href: "/trainings",                     icon: "calendarCheck" },

  // Activity — recognition + ops queues
  { section: "Activity", label: "My Weekly Funds",    href: "/weekly-funds",                  icon: "wallet" },
  { section: "Activity", label: "Planning",           href: "/planning",                      icon: "clipboardList" },

  // Insights — read-and-think surfaces
  { section: "Insights", label: "Reports",            href: "/reports",                       icon: "fileText" },
  { section: "Insights", label: "Analytics",          href: "/analytics",                     icon: "barChart" },
  { section: "Insights", label: "Map View",           href: "/map",                           icon: "mapPin" },

  // Account — references + settings-adjacent
  { section: "Account",  label: "Messages",           href: "/messages",                      icon: "messageSquare" },
  { section: "Account",  label: "Resources",          href: "/resources",                     icon: "bookOpen" },
  { section: "Account",  label: "Leave & Holidays",   href: "/leave",                         icon: "calendarRange" },
];

// ─────────── Verification & Payment funnel ───────────
// The operations→finance pipeline: every completed activity must walk
// Completed → Evidence → Salesforce ID → PL verify → IA verify →
// Accountant → Paid. The biggest stage-to-stage drop is the bottleneck.
export type CceoFunnelStage = {
  key: string;
  label: string;
  count: number;
  /** Where this stage's records live, so the row drills through. */
  href: string;
};

export const cceoVerificationFunnel: CceoFunnelStage[] = [
  { key: "completed", label: "Completed activities", count: 32, href: "/my-plan" },
  { key: "evidence",  label: "Evidence uploaded",    count: 28, href: "/data-verification" },
  { key: "sfid",      label: "Salesforce ID entered", count: 21, href: "/data-verification" },
  { key: "pl",        label: "PL verified",          count: 18, href: "/approvals" },
  { key: "ia",        label: "IA verified",          count: 16, href: "/approvals" },
  { key: "accountant", label: "Sent to accountant",  count: 9,  href: "/disbursements" },
  { key: "paid",      label: "Paid / cleared",       count: 6,  href: "/disbursements" },
];

// ─────────── Risk & bottleneck board ───────────
// What needs attention, grouped by risk type. Each carries a count,
// the reason, the owner, a recommended action, and a route to act on it.
export type CceoRiskType =
  | "Planning"
  | "Execution"
  | "Verification"
  | "Partner"
  | "Payment"
  | "Performance";

export type CceoRiskItem = {
  type: CceoRiskType;
  count: number;
  reason: string;
  owner: string;
  action: string;
  href: string;
};

export const cceoRiskBoard: CceoRiskItem[] = [
  { type: "Planning",     count: 8, reason: "Schools stuck — current-cycle SSA is missing", owner: "CCEO",        action: "Complete SSA",        href: "/planning" },
  { type: "Execution",    count: 6, reason: "Scheduled activities not started",             owner: "CCEO",        action: "Start activities",    href: "/my-plan" },
  { type: "Verification", count: 7, reason: "Completed work missing a Salesforce ID",       owner: "CCEO / PL",   action: "Enter Salesforce IDs", href: "/data-verification" },
  { type: "Partner",      count: 3, reason: "Partner activities returned for correction",   owner: "Partner",     action: "Review returns",      href: "/my-targets" },
  { type: "Payment",      count: 4, reason: "Payments blocked at IA verification",          owner: "IA",          action: "Follow up IA",        href: "/approvals" },
  { type: "Performance",  count: 2, reason: "Districts behind on this quarter's visit target", owner: "CCEO",     action: "Rebalance the plan",  href: "/my-targets" },
];
