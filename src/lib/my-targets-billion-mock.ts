// My Targets — Operating View mock data.
//
// Powers the multi-scale OPERATIONAL target-tracking dashboard. Tracks
// the seven programmatic activity categories the CCEO is accountable
// for: Staff Visits · Partner Visits · Training · Cluster Meetings ·
// Most Significant Change (MSC) Stories · Exam Results · School Self
// Assessment (SSA) Completion.
//
// Finance / budget tracking lives on the Accounts and CCEO program
// dashboards — this surface is intentionally activity-shaped, not
// shilling-shaped.

// ────────── Header ──────────

export const myTargetsHeader = {
  eyebrow:   "My Targets · May 2026",
  greeting:  "Good morning",
  firstName: "Paul",
  dateLong:  "Thursday, May 14, 2026",
  weekNo:    2,
  weekTotal: 4,
  activeTasks: 11,
  filters: {
    financialYear: "FY 2025/26",
    quarter:       "Q4 (Apr–Jun)",
    month:         "May 2026",
    district:      "Gulu",
  },
};

// ────────── Hero — dark gradient with status tiles and CTAs ──────────

export type HeroStatusTile = {
  key: string;
  label: string;
  value: string;
  caption: string;
  tone: "good" | "watch" | "warn" | "neutral";
};

export const myTargetsHero = {
  quote:   "Lead with discipline. Finish strong.",
  subtext: "Every visit, every assessment, every story builds the cohort. Small daily execution compounds.",
  statusTiles: [
    { key: "fy_pace",   label: "FY Pace",        value: "+4%",      caption: "Ahead of plan",      tone: "good"    },
    { key: "quarter",   label: "Quarter Status", value: "On Track", caption: "Q4 closing strong",  tone: "good"    },
    { key: "critical",  label: "Critical Gaps",  value: "2",        caption: "Need attention",     tone: "warn"    },
    { key: "today",     label: "Today Target",   value: "7 tasks",  caption: "Visits & trainings", tone: "neutral" },
  ] as HeroStatusTile[],
  primaryCta:   { label: "Review This Week", href: "/planning" },
  secondaryCta: { label: "Open My Plan",     href: "/planning" },
};

// ────────── 4-tier Target Cascade (FY → Q → M → D) ──────────
//
// Tracks ACTIVITY COUNTS, not money. "Activities" = the seven
// programmatic categories combined.

export type CascadeTone   = "good" | "watch" | "warn";
export type CascadeStatus = "On Track" | "Slightly Behind" | "Critical";

export type TargetCascadeTile = {
  index: number;
  label: string;
  amount: string;       // "342"  — completed
  total: string;        // "356 activities" — denominator
  pct: number;
  paceLabel: string;
  paceTone: CascadeTone;
  status: CascadeStatus;
  detail: string;
};

export const targetCascade: TargetCascadeTile[] = [
  { index: 1, label: "FINANCIAL YEAR TARGET",  amount: "342", total: "356 activities", pct: 96, paceLabel: "+4% ahead of pace",  paceTone: "good",  status: "On Track",        detail: "6 of 7 categories on track" },
  { index: 2, label: "QUARTERLY TARGET (Q4)",  amount: "88",  total: "96 activities",  pct: 92, paceLabel: "+2% ahead of pace",  paceTone: "good",  status: "On Track",        detail: "5 of 7 categories on track" },
  { index: 3, label: "MONTHLY TARGET (MAY)",   amount: "26",  total: "30 activities",  pct: 87, paceLabel: "-3% behind pace",    paceTone: "watch", status: "Slightly Behind", detail: "2 of 7 categories behind"   },
  { index: 4, label: "DAILY TARGET (TODAY)",   amount: "5",   total: "7 activities",   pct: 71, paceLabel: "-29% behind pace",   paceTone: "warn",  status: "Critical",        detail: "5 of 7 tasks pending"       },
];

// ────────── Target Categories Progress matrix ──────────
//
// Seven programmatic categories tracked across FY / Q4 / May / Today.

export type CategoryRowStatus = "Critical" | "On Track" | "Slightly Behind";

export type CategoryProgressRow = {
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
  todayPct: number | null;
  targetAchieved: string; // e.g. "10 / 9" — month target / achieved
  status: CategoryRowStatus;
};

export const categoryProgress: CategoryProgressRow[] = [
  { key: "staff_visits",   category: "Staff Visits",                icon: "staffVisit",   fyPct: 86, q4Pct: 90,  mayPct: 90, todayPct: 50,  targetAchieved: "10 / 9", status: "On Track"        },
  { key: "partner_visits", category: "Partner Visits",              icon: "partnerVisit", fyPct: 92, q4Pct: 95,  mayPct: 100,todayPct: 100, targetAchieved: "6 / 6",  status: "On Track"        },
  { key: "training",       category: "Training",                    icon: "training",     fyPct: 88, q4Pct: 92,  mayPct: 100,todayPct: 100, targetAchieved: "4 / 4",  status: "On Track"        },
  { key: "cluster",        category: "Cluster Meetings",            icon: "cluster",      fyPct: 95, q4Pct: 100, mayPct: 100,todayPct: 100, targetAchieved: "2 / 2",  status: "On Track"        },
  { key: "msc",            category: "Most Significant Change",     icon: "msc",          fyPct: 72, q4Pct: 80,  mayPct: 50, todayPct: 0,   targetAchieved: "2 / 1",  status: "Slightly Behind" },
  { key: "exam",           category: "Exam Results",                icon: "exam",         fyPct: 100,q4Pct: 100, mayPct: 100,todayPct: null,targetAchieved: "1 / 1",  status: "On Track"        },
  { key: "ssa",            category: "School Self Assessment (SSA)",icon: "ssa",          fyPct: 70, q4Pct: 75,  mayPct: 60, todayPct: 0,   targetAchieved: "5 / 3",  status: "Critical"        },
];

// ────────── Pace & Forecast ──────────
//
// Weekly breakdown is now activity counts (planned / completed /
// remaining), not UGX amounts.

export type PacePoint = {
  week: string;
  expected: number;
  actual: number | null;
};

export type WeeklyBreakdownRow = {
  week: string;
  plannedCount: number;
  completedCount: number;
  remainingCount: number;
  active: boolean;
};

export const paceForecast = {
  status: "Slightly Behind" as const,
  currentPct: 43,
  chart: [
    { week: "Week 1", expected: 25,  actual: 27 },   // ahead in week 1
    { week: "Week 2", expected: 50,  actual: 43 },   // currently slightly behind
    { week: "Week 3", expected: 75,  actual: null },
    { week: "Week 4", expected: 100, actual: null },
  ] as PacePoint[],
  weekly: [
    { week: "Week 1", plannedCount: 8, completedCount: 8, remainingCount: 0, active: false },
    { week: "Week 2", plannedCount: 8, completedCount: 5, remainingCount: 3, active: true  },
    { week: "Week 3", plannedCount: 7, completedCount: 0, remainingCount: 7, active: false },
    { week: "Week 4", plannedCount: 7, completedCount: 0, remainingCount: 7, active: false },
  ] as WeeklyBreakdownRow[],
  forecastPct:  87,
  forecastNote: "of target if current pace holds",
};

// ────────── Today Focus ──────────

export type TodayCategoryRow = {
  key: string;
  label: string;
  doneText: string;             // "2 / 1 done"
  tone: "good" | "warn" | "neutral";
};

export type TodayBlocker = {
  key: string;
  letter: string;
  text: string;
  count: number;
};

export const todayFocus = {
  status: "Critical" as const,
  kpis: {
    planned:       7,
    completed:     2,
    inProgress:    0,
    pending:       5,
    completionPct: 29,
  },
  categories: [
    { key: "staff_visits",   label: "Staff Visits",            doneText: "2 / 3 done", tone: "warn"    },
    { key: "partner_visits", label: "Partner Visits",          doneText: "0 / 1 done", tone: "warn"    },
    { key: "training",       label: "Training",                doneText: "0 / 1 done", tone: "warn"    },
    { key: "cluster",        label: "Cluster Meetings",        doneText: "0 / 1 done", tone: "neutral" },
    { key: "msc",            label: "Most Significant Change", doneText: "0 / 0 done", tone: "neutral" },
    { key: "ssa",            label: "SSA Completion",          doneText: "0 / 1 done", tone: "warn"    },
  ] as TodayCategoryRow[],
  blockers: [
    { key: "blocker_overdue", letter: "A", text: "Overdue visits this week",   count: 3 },
    { key: "blocker_route",   letter: "B", text: "Route quality issue",        count: 1 },
    { key: "blocker_partner", letter: "C", text: "Partner unavailable",        count: 0 },
  ] as TodayBlocker[],
  quickActions: [
    { key: "plan_visit",    label: "Plan Visit",    icon: "calendar" as const },
    { key: "open_route",    label: "Open Route",    icon: "route"    as const },
    { key: "notify_lead",   label: "Notify Lead",   icon: "bell"     as const },
    { key: "update_status", label: "Update Status", icon: "refresh"  as const },
  ],
  debriefHelp:   "Pre-filled from your todo list — update & submit before end of day.",
  blockerChips: [
    "School closed",
    "Route delay",
    "Partner no-show",
    "SSA materials missing",
    "Exam day clash",
  ],
};

// ────────── Daily debrief recent entries ──────────
//
// Last few days of debriefs surfaced inside the Daily Debrief card so
// the CCEO can see their continuity at a glance and compare today's
// reflection against the trailing week.

export type DebriefEntry = {
  key:     string;
  date:    string;   // "May 13"
  note:    string;
  tags:    string[];
};

export const recentDebriefs: DebriefEntry[] = [
  {
    key:  "deb-2026-05-13",
    date: "May 13",
    note: "Completed 2 staff visits + 1 SSA at Cornerstone. Stayed on pace.",
    tags: ["Route delay"],
  },
  {
    key:  "deb-2026-05-12",
    date: "May 12",
    note: "3 visits done. Submitted MSC story draft for Bright Future.",
    tags: [],
  },
  {
    key:  "deb-2026-05-11",
    date: "May 11",
    note: "Cluster meeting attended. School closed at Maryhill — rebooked.",
    tags: ["School closed"],
  },
];

// ────────── Needs Attention ──────────

export type NeedsAttentionItem = {
  key: string;
  title: string;
  detail: string;
  severity: "Critical" | "High";
};

export const needsAttention = {
  criticalCount: 2,
  items: [
    { key: "ssa", title: "SSA Completion behind by 40%",         detail: "5 SSA assessments planned this month — 3 completed.", severity: "Critical" },
    { key: "msc", title: "MSC Stories at 50% mid-month",          detail: "2 stories planned, 1 documented — surface one more this week.", severity: "High"     },
    { key: "sv",  title: "Staff Visits 1 behind expected pace",   detail: "10 staff visits planned — 9 completed, 1 still pending today.", severity: "High"     },
  ] as NeedsAttentionItem[],
};

// ────────── Recovery Actions ──────────

export type RecoveryAction = {
  key: string;
  text: string;
};

export const recoveryActions: RecoveryAction[] = [
  { key: "ra1", text: "Complete 2 SSA assessments by end of week." },
  { key: "ra2", text: "Draft 1 Most Significant Change story today." },
  { key: "ra3", text: "Close the 1 pending staff visit before Friday." },
  { key: "ra4", text: "Unblock 3 overdue visits with route coordinator." },
];

// ────────── Achievement & Momentum ──────────

export const achievementMomentum = {
  streak: {
    label:   "Consistency Streak",
    value:   "12",
    unit:    "days",
    caption: "On-time daily planning",
  },
  bestMonth: {
    label:    "Best This Month",
    category: "Partner Visits",
    pct:      "100%",
    trend:    "+12% vs last month",
  },
  recognition: {
    label:    "Recognition",
    title:    "Best Performing CCEO",
    person:   "Grace Nansubuga",
    region:   "Central",
    verified: "94% Verified Achievement",
  },
};

// ────────── Footer mini-metrics ──────────
//
// Programmatic, NOT financial. Finance lives on Accounts / CCEO
// program dashboards; this strip is the activity scorecard.

export type FooterMetric = {
  key: string;
  label: string;
  value: string;
  caption: string;
};

export const footerMetrics: FooterMetric[] = [
  { key: "verified_visits", label: "Verified Visits",     value: "126",       caption: "Staff + Partner combined"        },
  { key: "ssa_progress",    label: "SSAs This FY",        value: "48 / 60",   caption: "80% complete"                    },
  { key: "trainings",       label: "Trainings Delivered", value: "32",        caption: "+8 vs prior month"               },
  { key: "msc_stories",     label: "MSC Stories",         value: "12 / 16",   caption: "4 stories outstanding"           },
  { key: "annual_coverage", label: "Annual Coverage",     value: "560 / 600", caption: "93% of target schools"           },
  { key: "exam_results",    label: "Exam Results",        value: "Q4 ✓",      caption: "All schools reported"            },
  { key: "last_sync",       label: "Last Sync",           value: "2 min ago", caption: "All data up to date"             },
];
