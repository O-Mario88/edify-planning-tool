// Core School Dashboard — replica mock layer.
//
// Numbers are pinned to the design reference (FY 2025, Q2). This file
// exists separately from the live `core-schools-mock.ts` engine so the
// per-row filtering used by /core-schools doesn't strip the headline
// counts the executive dashboard needs to render meaningful KPIs.
//
// When the real backend lands, every export here swaps to `db.*` (one
// query per row group) without UI changes.

// ────────── 9 KPI tiles ──────────

export type ReplicaKpiVisual =
  | { kind: "bars";  values: number[]  }
  | { kind: "line";  values: number[]  }
  | { kind: "ring";  pct: number; tone: "emerald" | "amber" | "rose" }
  | { kind: "brand"; label: string };

export type ReplicaKpi = {
  key:        string;
  label:      string;
  value:      string;          // "512", "92.1%"
  subValue?:  string;          // "Across 8 Districts", "(90.2%)"
  delta?:     string;          // "+6.5%", "-2.1%"
  deltaTone?: "up" | "down";
  caption?:   string;          // "vs Apr 2025"
  visual:     ReplicaKpiVisual;
};

// 7 distinct KPIs — Package Complete and Potential Champions were
// removed because they're already surfaced as stages in the 8-tile
// Core Service Package Progress funnel below (4V+4T and the final
// Potential Champion tile carry the same numbers). Keeping them as
// standalone KPIs created double-counting in the user's read.
export const replicaKpis: ReplicaKpi[] = [
  { key: "total",       label: "Total Core Schools",       value: "512", subValue: "Across 8 Districts",
    visual: { kind: "bars", values: [380, 420, 440, 470, 488, 498, 506, 512] } },
  { key: "assessed",    label: "Core Schools Assessed",    value: "462", subValue: "(90.2%)",
    delta: "+6.5%", deltaTone: "up", caption: "vs Apr 2025",
    visual: { kind: "bars", values: [310, 350, 380, 405, 420, 438, 450, 462] } },
  { key: "avg_ssa",     label: "Average Core SSA Score",   value: "7.6", subValue: "/10",
    delta: "+0.4",  deltaTone: "up", caption: "vs Apr 2025",
    visual: { kind: "line", values: [6.8, 6.9, 7.0, 7.1, 7.2, 7.3, 7.4, 7.6] } },
  { key: "on_track",    label: "On Track",                  value: "286", subValue: "(55.9%)",
    delta: "+4.3%", deltaTone: "up", caption: "vs Apr 2025",
    visual: { kind: "ring", pct: 55.9, tone: "emerald" } },
  { key: "behind",      label: "Behind Schedule",           value: "148", subValue: "(28.9%)",
    delta: "-2.1%", deltaTone: "down", caption: "vs Apr 2025",
    visual: { kind: "ring", pct: 28.9, tone: "amber" } },
  { key: "critical",    label: "Critical Gap",              value: "78",  subValue: "(15.2%)",
    delta: "-2.2%", deltaTone: "down", caption: "vs Apr 2025",
    visual: { kind: "ring", pct: 15.2, tone: "rose" } },
  { key: "salesforce",  label: "Salesforce Compliance",     value: "92.1%",
    delta: "+3.4%", deltaTone: "up", caption: "vs Apr 2025",
    visual: { kind: "brand", label: "Salesforce" } },
];

// ────────── Service Package Progress (8 tiles + summary + remaining) ──────────

export type ReplicaPackageTile = {
  key:    string;
  label:  string;
  count:  number;
  pct:    number;
  icon:   "doc" | "calendar" | "users" | "step1" | "step2" | "step3" | "schoolCheck" | "trophy";
  tone:   "slate" | "rose" | "amber" | "blue" | "violet" | "indigo" | "green" | "yellow";
};

export const replicaPackageTiles: ReplicaPackageTile[] = [
  { key: "0ssa",   label: "0 SSA",                 count: 50,  pct: 9.8,  icon: "doc",         tone: "slate"  },
  { key: "0v",     label: "0 Visits",              count: 42,  pct: 8.2,  icon: "calendar",    tone: "rose"   },
  { key: "0t",     label: "0 Training",            count: 39,  pct: 7.6,  icon: "users",       tone: "amber"  },
  { key: "1v1t",   label: "1 Visit + 1 Training",  count: 71,  pct: 13.9, icon: "step1",       tone: "blue"   },
  { key: "2v2t",   label: "2 Visits + 2 Trainings", count: 96, pct: 18.8, icon: "step2",       tone: "violet" },
  { key: "3v3t",   label: "3 Visits + 3 Trainings", count: 84, pct: 16.4, icon: "step3",       tone: "indigo" },
  { key: "4v4t",   label: "4 Visits + 4 Trainings", count: 130, pct: 25.4, icon: "schoolCheck", tone: "green"  },
  { key: "champ",  label: "Potential Champions",   count: 58,  pct: 11.3, icon: "trophy",      tone: "yellow" },
];

export const replicaMinimumCoreSupport = { pct: 65.9 };

export const replicaRemainingTasks = [
  { key: "visits",        label: "schools need 2+ more visits",    count: 128, tone: "blue"  as const, icon: "calendar"     as const },
  { key: "trainings",     label: "schools need 1 more training",   count: 94,  tone: "amber" as const, icon: "graduationCap" as const },
  { key: "verifications", label: "schools need final verification", count: 42, tone: "green" as const, icon: "shieldCheck"  as const },
];

// ────────── SSA Trend (Jul → Jun) ──────────

export type ReplicaTrendPoint = { month: string; score: number };
export const replicaSsaTrend: ReplicaTrendPoint[] = [
  { month: "Jul", score: 6.9 },
  { month: "Aug", score: 7.0 },
  { month: "Sep", score: 7.1 },
  { month: "Oct", score: 7.2 },
  { month: "Nov", score: 7.0 },
  { month: "Dec", score: 7.1 },
  { month: "Jan", score: 7.2 },
  { month: "Feb", score: 7.1 },
  { month: "Mar", score: 7.2 },
  { month: "Apr", score: 7.2 },
  { month: "May", score: 7.4 },
  { month: "Jun", score: 7.6 },
];

// ────────── SSA Performance by Intervention (8 bars) ──────────

export type ReplicaInterventionRow = { intervention: string; score: number; rank: number };
export const replicaInterventionScores: ReplicaInterventionRow[] = [
  { rank: 1, intervention: "Christ-like Behavior",         score: 8.4 },
  { rank: 2, intervention: "Exposure to the Word of God",  score: 8.1 },
  { rank: 3, intervention: "Fees / Budget / Accounts",     score: 7.8 },
  { rank: 4, intervention: "Government Requirements",      score: 7.4 },
  { rank: 5, intervention: "Leadership Best Practice",     score: 7.4 },
  { rank: 6, intervention: "Learning Environment",         score: 7.2 },
  { rank: 7, intervention: "Teaching Environment",         score: 6.6 },
  { rank: 8, intervention: "Enrollment",                   score: 6.2 },
];

// ────────── Core SSA Heatmap by District ──────────

export type ReplicaHeatmapRow = {
  district:   string;
  ssaAvg:     number;
  christlike: number;
  wordOfGod:  number;
  leadership: number;
  teaching:   number;
  enrollment: number;
  avgRow:     number;
};

export const replicaHeatmap: ReplicaHeatmapRow[] = [
  { district: "Lusaka",       ssaAvg: 8.3, christlike: 8.2, wordOfGod: 7.9, leadership: 7.9, teaching: 7.1, enrollment: 7.1, avgRow: 7.7 },
  { district: "Ndola",        ssaAvg: 7.9, christlike: 7.8, wordOfGod: 7.6, leadership: 7.6, teaching: 6.4, enrollment: 7.2, avgRow: 7.2 },
  { district: "Kitwe",        ssaAvg: 7.6, christlike: 7.4, wordOfGod: 7.1, leadership: 6.8, teaching: 6.5, enrollment: 6.9, avgRow: 7.0 },
  { district: "Chipata",      ssaAvg: 7.2, christlike: 7.0, wordOfGod: 6.8, leadership: 6.6, teaching: 5.8, enrollment: 6.7, avgRow: 6.7 },
  { district: "Mufulira",     ssaAvg: 6.8, christlike: 6.6, wordOfGod: 6.4, leadership: 6.3, teaching: 5.6, enrollment: 6.3, avgRow: 6.3 },
  { district: "Solwezi",      ssaAvg: 6.4, christlike: 6.4, wordOfGod: 6.2, leadership: 7.0, teaching: 6.2, enrollment: 7.3, avgRow: 6.6 },
  { district: "Kabwe",        ssaAvg: 7.1, christlike: 7.0, wordOfGod: 7.2, leadership: 6.8, teaching: 5.4, enrollment: 6.5, avgRow: 6.5 },
  { district: "Chillalombwe", ssaAvg: 6.6, christlike: 6.4, wordOfGod: 6.3, leadership: 6.1, teaching: 5.8, enrollment: 5.1, avgRow: 6.0 },
];

// ────────── Intervention Performance YoY ──────────

export type ReplicaYoyRow = {
  intervention: string;
  fy2024:       number;
  fy2025:       number;
  change:       number;
  trend:        number[];        // 6-point sparkline
};

export const replicaInterventionYoy: ReplicaYoyRow[] = [
  { intervention: "Christ-like Behavior",        fy2024: 8.1, fy2025: 8.4, change: 0.3, trend: [8.1, 8.1, 8.2, 8.3, 8.3, 8.4] },
  { intervention: "Exposure to the Word of God", fy2024: 7.9, fy2025: 8.1, change: 0.2, trend: [7.9, 7.9, 8.0, 8.0, 8.1, 8.1] },
  { intervention: "Fees / Budget / Accounts",    fy2024: 7.3, fy2025: 7.8, change: 0.5, trend: [7.3, 7.4, 7.5, 7.6, 7.7, 7.8] },
  { intervention: "Government Requirements",     fy2024: 6.9, fy2025: 7.4, change: 0.5, trend: [6.9, 7.0, 7.1, 7.2, 7.3, 7.4] },
  { intervention: "Leadership Best Practice",    fy2024: 6.9, fy2025: 7.4, change: 0.5, trend: [6.9, 7.0, 7.1, 7.2, 7.3, 7.4] },
  { intervention: "Learning Environment",        fy2024: 6.7, fy2025: 7.2, change: 0.5, trend: [6.7, 6.8, 6.9, 7.0, 7.1, 7.2] },
  { intervention: "Teaching Environment",        fy2024: 6.1, fy2025: 6.6, change: 0.5, trend: [6.1, 6.2, 6.3, 6.4, 6.5, 6.6] },
  { intervention: "Enrollment",                  fy2024: 5.8, fy2025: 6.2, change: 0.4, trend: [5.8, 5.9, 6.0, 6.0, 6.1, 6.2] },
];

// ────────── Best Performing Core Schools ──────────

export type ReplicaBestRow = {
  rank:        number;
  schoolName:  string;
  district:    string;
  cceo:        string;
  ssaAvg:      number;
  improvement: number;       // YoY
  visits:      string;       // "4/4"
  trainings:   string;       // "4/4"
  packageStatus:          "Complete" | "Nearly Complete";
  salesforceCompliance:   number;  // 96, 98, etc.
  championRecommendation: "Champion Review" | "Potential Champion";
};

export const replicaBestPerforming: ReplicaBestRow[] = [
  { rank: 1, schoolName: "Faith Lighthouse Academy",    district: "Lusaka",   cceo: "P. Chinyama", ssaAvg: 9.2, improvement: 1.2, visits: "4/4", trainings: "4/4", packageStatus: "Complete",        salesforceCompliance: 100, championRecommendation: "Champion Review"   },
  { rank: 2, schoolName: "Living Word School",          district: "Solwezi",  cceo: "M. Banda",    ssaAvg: 8.9, improvement: 0.9, visits: "4/4", trainings: "4/4", packageStatus: "Complete",        salesforceCompliance: 98,  championRecommendation: "Potential Champion" },
  { rank: 3, schoolName: "Grace Community School",      district: "Lusaka",   cceo: "P. Chinyama", ssaAvg: 8.7, improvement: 1.5, visits: "4/4", trainings: "4/4", packageStatus: "Complete",        salesforceCompliance: 97,  championRecommendation: "Potential Champion" },
  { rank: 4, schoolName: "Hope International School",   district: "Ndola",    cceo: "J. Phiri",    ssaAvg: 8.5, improvement: 1.1, visits: "4/4", trainings: "4/4", packageStatus: "Complete",        salesforceCompliance: 95,  championRecommendation: "Potential Champion" },
  { rank: 5, schoolName: "Victory Academy",             district: "Kitwe",    cceo: "E. Mutale",   ssaAvg: 8.3, improvement: 0.7, visits: "3/4", trainings: "3/4", packageStatus: "Nearly Complete", salesforceCompliance: 96,  championRecommendation: "Potential Champion" },
  { rank: 6, schoolName: "Bright Future School",        district: "Mufulira", cceo: "M. Banda",    ssaAvg: 8.1, improvement: 0.6, visits: "3/4", trainings: "3/4", packageStatus: "Nearly Complete", salesforceCompliance: 93,  championRecommendation: "Potential Champion" },
  { rank: 7, schoolName: "Cornerstone School",          district: "Kitwe",    cceo: "E. Mutale",   ssaAvg: 8.0, improvement: 0.8, visits: "3/4", trainings: "3/4", packageStatus: "Nearly Complete", salesforceCompliance: 94,  championRecommendation: "Champion Review"   },
];

// ────────── Core Schools Needing More Attention ──────────

export type ReplicaAttentionRow = {
  schoolName:        string;
  district:          string;
  cceo:              string;
  ssaScore:          number;
  lowestIntervention: string;
  visitsCompleted:   string;  // "0/4"
  trainingsCompleted: string;
  gapToPackage:      number;
  riskReason:        string;
  recommendedAction: string;
  riskTone:          "rose" | "amber" | "violet";
};

export const replicaAttention: ReplicaAttentionRow[] = [
  { schoolName: "New Dawn School",      district: "Chipata",      cceo: "J. Phiri",    ssaScore: 5.2, lowestIntervention: "Enrollment", visitsCompleted: "0/4", trainingsCompleted: "0/4", gapToPackage: 4, riskReason: "No SSA, No Visits, No Trainings", recommendedAction: "Schedule SSA assessment & initial visit", riskTone: "rose" },
  { schoolName: "Bright Future School", district: "Mufulira",     cceo: "M. Banda",    ssaScore: 5.2, lowestIntervention: "Fees / Budget", visitsCompleted: "1/4", trainingsCompleted: "1/4", gapToPackage: 3, riskReason: "Low SSA, Behind Schedule", recommendedAction: "Complete training 1 & 2 and next visit", riskTone: "amber" },
  { schoolName: "Unity Christian School", district: "Kabwe",      cceo: "E. Mutale",   ssaScore: 5.6, lowestIntervention: "Teaching Env.", visitsCompleted: "1/4", trainingsCompleted: "0/4", gapToPackage: 3, riskReason: "No Training, Behind Schedule", recommendedAction: "Schedule Training 1", riskTone: "violet" },
  { schoolName: "Redeemer School",      district: "Chillalombwe", cceo: "J. Phiri",    ssaScore: 5.9, lowestIntervention: "Enrollment", visitsCompleted: "0/4", trainingsCompleted: "1/4", gapToPackage: 3, riskReason: "No Visits, Behind Schedule", recommendedAction: "Plan and conduct first visit", riskTone: "rose" },
  { schoolName: "Grace Hill School",    district: "Lusaka",       cceo: "P. Chinyama", ssaScore: 6.0, lowestIntervention: "Leadership", visitsCompleted: "1/4", trainingsCompleted: "1/4", gapToPackage: 2, riskReason: "Low SSA, Behind Schedule", recommendedAction: "Improve interventions & complete training", riskTone: "amber" },
  { schoolName: "River Valley School",  district: "Kitwe",        cceo: "E. Mutale",   ssaScore: 6.1, lowestIntervention: "Fees / Budget", visitsCompleted: "2/4", trainingsCompleted: "1/4", gapToPackage: 2, riskReason: "Behind Schedule", recommendedAction: "Complete remaining visits", riskTone: "amber" },
];

// ────────── Champion School Pipeline ──────────

export const replicaChampionPipeline = {
  total:       58,
  totalLabel:  "Schools",
  segments: [
    { key: "ineligible", label: "Not Eligible",            count: 454, pct: 88.7, color: "#cbd5e1" },
    { key: "potential",  label: "Potential Champion",       count: 46,  pct: 9.0,  color: "#3b82f6" },
    { key: "review",     label: "Champion Review Required", count: 12,  pct: 2.3,  color: "#f59e0b" },
    { key: "recommended", label: "Recommended as Champion", count: 18,  pct: 3.5,  color: "#10b981" },
    { key: "approved",   label: "Approved Champion School", count: 6,   pct: 1.2,  color: "#059669" },
  ],
};

// ────────── Follow-Up Alerts ──────────

export type ReplicaAlert = {
  key:    string;
  title:  string;
  count:  number;
  body:   string;
  icon:   "calendarClock" | "calendar" | "alertOctagon";
  tone:   "rose" | "amber" | "orange";
};

export const replicaFollowUpAlerts: ReplicaAlert[] = [
  { key: "overdue",   title: "Trainings Overdue",        count: 12, body: "Require immediate attention",  icon: "calendarClock", tone: "rose"   },
  { key: "due_month", title: "Trainings Due This Month", count: 36, body: "Schedule to stay on track",    icon: "calendar",       tone: "amber"  },
  { key: "behind",    title: "Schools Behind Schedule",  count: 84, body: "Risk of falling further behind", icon: "alertOctagon", tone: "orange" },
];

// ────────── Core Package Remaining Tasks (bottom-right card) ──────────

export type ReplicaPackageTask = {
  key:   string;
  label: string;
  count: number;
  icon:  "footprints" | "graduationCap" | "shieldCheck" | "fileText";
};

export const replicaPackageTasks: ReplicaPackageTask[] = [
  { key: "visits",        label: "Visits Remaining",         count: 248, icon: "footprints"    },
  { key: "trainings",     label: "Trainings Remaining",      count: 196, icon: "graduationCap" },
  { key: "verifications", label: "Final Verifications",      count: 42,  icon: "shieldCheck"   },
  { key: "ssa",           label: "SSA Assessments Pending",  count: 50,  icon: "fileText"      },
];

export const replicaPackageTaskTotal = 536;

// ────────── Filter bar options ──────────

export const replicaFilters = {
  fy:           { label: "FY 2025",         caption: "Jul 2024 – Jun 2025" },
  quarter:      { label: "Q2",              caption: "Apr – Jun 2025"      },
  regions:      { label: "All Regions" },
  districts:    { label: "All Districts" },
  clusters:     { label: "All Clusters" },
  cceos:        { label: "All CCEOs" },
  partners:     { label: "All Partners" },
  packageStatus:{ label: "All Package Status" },
  ssaStatus:    { label: "All SSA Status" },
  champStatus:  { label: "All Champion Status" },
};

// ────────── Sidebar identity (UCU brand) ──────────

export const replicaBrand = {
  short:      "UCU",
  tagline:    "Impacting Lives,\nTransforming Nations",
  sectionLabel: "CORE SCHOOL",
  footerLine: "© 2025 United Church of Zambia (UCU)",
  buildLabel: "v3.2.1",
  dataAsOf:   "Jun 30, 2025 11:59 PM",
  quote:      "Every school you support today shapes a generation that will transform a nation tomorrow.",
  quoteSign:  "Keep leading. God is building something eternal through your obedience.",
};

// ────────── Profile + header text ──────────

export const replicaHeaderProfile = {
  name:      "Paul Chinyama",
  initials:  "PC",
  role:      "CCEO",
  online:    true,
  avatarUrl: null as string | null,
};

export const replicaHeaderText = {
  title:    "Core School Dashboard",
  subtitle: "Track Core School service package completion, SSA performance, risk, and Champion School readiness.",
  notificationsCount: 12,
};
