// Team Targets — billion-dollar Operating View mock data.
//
// Mirrors the my-targets billion shape but expresses every value at
// TEAM level: aggregate activity counts across the supervised CCEO
// roster, staff-distribution percentages, regional rollups, and the
// program-lead actions that fix gaps.

// ────────── Header ──────────

export const teamTargetsBillionHeader = {
  eyebrow:   "Team Targets · May 2026",
  greeting:  "Good morning",
  firstName: "Daniel",
  dateLong:  "Thursday, May 14, 2026",
  weekNo:    2,
  weekTotal: 4,
  staffCount: 144,
  filters: {
    financialYear: "FY 2025/26",
    quarter:       "Q4 (Apr–Jun)",
    month:         "May 2026",
    region:        "All Regions",
  },
};

// ────────── Hero — dark gradient with status tiles and CTAs ──────────

export type TeamHeroTone = "good" | "watch" | "warn" | "neutral";

export type TeamHeroStatusTile = {
  key: string;
  label: string;
  value: string;
  caption: string;
  tone: TeamHeroTone;
};

export const teamTargetsBillionHero = {
  quote:   "Lift the team. Close the gap.",
  subtext: "Every staff visit, every catch-up plan, every coaching call moves the cohort closer to target.",
  statusTiles: [
    { key: "team_pace",  label: "Team Pace",       value: "+5%",       caption: "Ahead of plan",       tone: "good"    },
    { key: "on_track",   label: "Staff On Track",  value: "62 / 144",  caption: "43% of cohort",       tone: "good"    },
    { key: "at_risk",    label: "At Risk",         value: "36",        caption: "Need intervention",   tone: "warn"    },
    { key: "this_week",  label: "This Week",       value: "1,264",     caption: "Activities logged",   tone: "neutral" },
  ] as TeamHeroStatusTile[],
  primaryCta:   { label: "Open Support Reviews", href: "/team-targets" },
  secondaryCta: { label: "Review High-Risk Staff", href: "/team-targets" },
};

// ────────── 4-tier Team Cascade (FY → Q → M → W) ──────────

export type TeamCascadeTone   = "good" | "watch" | "warn";
export type TeamCascadeStatus = "On Track" | "Slightly Behind" | "Critical";

export type TeamCascadeTile = {
  index: number;
  label: string;
  amount: string;
  total: string;
  pct: number;
  paceLabel: string;
  paceTone: TeamCascadeTone;
  status: TeamCascadeStatus;
  detail: string;
};

export const teamCascade: TeamCascadeTile[] = [
  { index: 1, label: "FINANCIAL YEAR TARGET",   amount: "4,280", total: "4,520 activities", pct: 95, paceLabel: "+5% ahead of pace", paceTone: "good",  status: "On Track",        detail: "5 of 7 categories on track" },
  { index: 2, label: "QUARTERLY TARGET (Q4)",   amount: "1,180", total: "1,280 activities", pct: 92, paceLabel: "+2% ahead of pace", paceTone: "good",  status: "On Track",        detail: "5 of 7 categories on track" },
  { index: 3, label: "MONTHLY TARGET (MAY)",    amount: "285",   total: "320 activities",   pct: 89, paceLabel: "-2% behind pace",   paceTone: "watch", status: "Slightly Behind", detail: "2 of 7 categories behind"   },
  { index: 4, label: "THIS WEEK (WEEK 2)",      amount: "68",    total: "85 activities",    pct: 80, paceLabel: "-7% behind pace",   paceTone: "watch", status: "Slightly Behind", detail: "Recovery focus on SSA"      },
];

// ────────── Team Categories Progress matrix ──────────

export type TeamCategoryRowStatus = "Critical" | "On Track" | "Slightly Behind";

export type TeamCategoryProgressRow = {
  key: string;
  category: string;
  icon:
    | "staffVisit"
    | "partnerVisit"
    | "training"
    | "cluster"
    | "msc"
    | "exam"
    | "ssa";
  fyPct: number;
  q4Pct: number;
  mayPct: number;
  weekPct: number | null;
  targetAchieved: string;
  status: TeamCategoryRowStatus;
};

export const teamCategoryProgress: TeamCategoryProgressRow[] = [
  { key: "staff_visits",   category: "Staff Visits",                icon: "staffVisit",   fyPct: 88,  q4Pct: 92,  mayPct: 90, weekPct: 78, targetAchieved: "1,248 / 1,389", status: "On Track"        },
  { key: "partner_visits", category: "Partner Visits",              icon: "partnerVisit", fyPct: 94,  q4Pct: 96,  mayPct: 95, weekPct: 100, targetAchieved: "1,118 / 1,180", status: "On Track"        },
  { key: "training",       category: "Training",                    icon: "training",     fyPct: 90,  q4Pct: 95,  mayPct: 88, weekPct: 100, targetAchieved: "72 / 80",       status: "On Track"        },
  { key: "cluster",        category: "Cluster Meetings",            icon: "cluster",      fyPct: 95,  q4Pct: 100, mayPct: 100,weekPct: 100, targetAchieved: "18 / 18",       status: "On Track"        },
  { key: "msc",            category: "Most Significant Change",     icon: "msc",          fyPct: 72,  q4Pct: 78,  mayPct: 60, weekPct: 25,  targetAchieved: "16 / 24",       status: "Slightly Behind" },
  { key: "exam",           category: "Exam Results",                icon: "exam",         fyPct: 100, q4Pct: 100, mayPct: 100,weekPct: null,targetAchieved: "12 / 12",       status: "On Track"        },
  { key: "ssa",            category: "School Self Assessment (SSA)",icon: "ssa",          fyPct: 70,  q4Pct: 75,  mayPct: 65, weekPct: 0,   targetAchieved: "734 / 1,200",   status: "Critical"        },
];

// ────────── Pace & Forecast ──────────

export type TeamPacePoint = {
  week: string;
  expected: number;
  actual: number | null;
};

export type TeamWeeklyBreakdownRow = {
  week: string;
  plannedCount: number;
  completedCount: number;
  remainingCount: number;
  active: boolean;
};

export const teamPaceForecast = {
  status: "Slightly Behind" as const,
  currentPct: 68,
  chart: [
    { week: "Week 1", expected: 25,  actual: 28 },
    { week: "Week 2", expected: 50,  actual: 43 },
    { week: "Week 3", expected: 75,  actual: null },
    { week: "Week 4", expected: 100, actual: null },
  ] as TeamPacePoint[],
  weekly: [
    { week: "Week 1", plannedCount: 460, completedCount: 480, remainingCount: 0,   active: false },
    { week: "Week 2", plannedCount: 480, completedCount: 320, remainingCount: 160, active: true  },
    { week: "Week 3", plannedCount: 460, completedCount: 0,   remainingCount: 460, active: false },
    { week: "Week 4", plannedCount: 450, completedCount: 0,   remainingCount: 450, active: false },
  ] as TeamWeeklyBreakdownRow[],
  forecastPct:  87,
  forecastNote: "of target if current pace holds",
};

// ────────── Staff Needs Support ──────────

export type StaffNeedsSupportItem = {
  key: string;
  staffName: string;
  initials: string;
  region: string;
  achievementPct: number;
  trigger: "Mid-Year Below 40%" | "Early Warning" | "Critical Target Risk";
  gap: string;            // "-28 activities" / "Missing 3 SSAs"
  severity: "Critical" | "High";
};

export const staffNeedsSupport = {
  criticalCount: 3,
  highCount:     2,
  items: [
    { key: "ah-044", staffName: "Abdi Hassan",      initials: "AH", region: "North",   achievementPct: 32, trigger: "Mid-Year Below 40%",   gap: "-36 activities",         severity: "Critical" },
    { key: "pm-052", staffName: "Purity Muthoni",   initials: "PM", region: "West",    achievementPct: 38, trigger: "Mid-Year Below 40%",   gap: "-28 activities",         severity: "Critical" },
    { key: "jo-022", staffName: "James Otieno",     initials: "JO", region: "Central", achievementPct: 46, trigger: "Critical Target Risk", gap: "-21 activities",         severity: "Critical" },
    { key: "pm-061", staffName: "Peter Mutua",      initials: "PM", region: "East",    achievementPct: 52, trigger: "Early Warning",        gap: "-24 activities · 0 SSA", severity: "High"     },
    { key: "mw-038", staffName: "Mary Wambui",      initials: "MW", region: "East",    achievementPct: 58, trigger: "Early Warning",        gap: "-12 activities",         severity: "High"     },
  ] as StaffNeedsSupportItem[],
};

// ────────── Top Performer ──────────

export const topTeamPerformer = {
  streak: {
    label:   "Team Streak",
    value:   "9",
    unit:    "weeks",
    caption: "Above target",
  },
  bestMover: {
    label:    "Biggest Mover",
    category: "Cluster Meetings",
    pct:      "100%",
    trend:    "+18% vs Apr",
  },
  recognition: {
    label:    "Top CCEO",
    title:    "May 2026",
    person:   "Grace Njeri",
    region:   "East",
    verified: "92% Verified Achievement",
  },
};

// ────────── Team Recovery Actions ──────────

export type TeamRecoveryAction = {
  key: string;
  text: string;
  scope: string;            // "Wajir & Mandera" / "144 staff" / etc.
};

export const teamRecoveryActions: TeamRecoveryAction[] = [
  { key: "tra1", text: "Open Support Review for 2 mid-year below-40% staff", scope: "North · West" },
  { key: "tra2", text: "Rebalance 12 visits from over-loaded to under-loaded staff", scope: "Central + East regions" },
  { key: "tra3", text: "Escalate Salesforce backlog with M&E (47 unresolved tickets)", scope: "Cross-region" },
  { key: "tra4", text: "Approve 4 catch-up plans submitted by CCEOs", scope: "Awaiting PL sign-off" },
];

// ────────── Team Status Distribution (mirrors the existing data) ──────────

export const teamStatusDistribution = {
  total: 144,
  buckets: [
    { key: "on_track",      label: "On Track",        countLabel: "≥ 80%",   count: 62, pct: 43, color: "#16a34a", tone: "good"  as const },
    { key: "slightly",      label: "Slightly Behind", countLabel: "60-79%",  count: 46, pct: 32, color: "#f59e0b", tone: "watch" as const },
    { key: "high_risk",     label: "High Risk",       countLabel: "40-59%",  count: 24, pct: 17, color: "#ef4444", tone: "warn"  as const },
    { key: "critical",      label: "Critical",        countLabel: "< 40%",   count: 12, pct: 8,  color: "#b91c1c", tone: "warn"  as const },
  ],
  regionsBehind: [
    { region: "North",   pct: 38, tone: "warn"  as const },
    { region: "East",    pct: 45, tone: "warn"  as const },
    { region: "West",    pct: 52, tone: "watch" as const },
    { region: "Central", pct: 65, tone: "watch" as const },
  ],
};

// ────────── Footer mini-metrics ──────────

export type TeamFooterMetric = {
  key: string;
  label: string;
  value: string;
  caption: string;
};

export const teamFooterMetrics: TeamFooterMetric[] = [
  { key: "verified",        label: "Verified Activities", value: "2,840",     caption: "Across 144 staff"             },
  { key: "ssa",             label: "SSAs This FY",        value: "734 / 1,200", caption: "61% complete"               },
  { key: "trainings",       label: "Trainings Delivered", value: "72 / 100",  caption: "Team-wide"                    },
  { key: "msc",             label: "MSC Stories",         value: "16 / 24",   caption: "8 outstanding"                },
  { key: "annual_coverage", label: "Annual Coverage",     value: "1,132 / 1,650", caption: "69% of target schools"   },
  { key: "support_reviews", label: "Open Support Reviews",value: "2",         caption: "1 in progress, 1 awaiting"   },
  { key: "last_sync",       label: "Last Sync",           value: "2 min ago", caption: "All data up to date"         },
];
