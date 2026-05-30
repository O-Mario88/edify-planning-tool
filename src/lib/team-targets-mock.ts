// Team Targets Dashboard — engine + mock data.
//
// CONTRACT (humane performance rule, non-negotiable):
//   • Early-warning detection runs from real target categories on a single
//     visible scope (CPL = supervised staff; CD = country; RVP = countries).
//   • Mid-year (≥ 50% of FY elapsed) AND below 40% across ALL major
//     categories is the only condition that surfaces "Possible PIP Review".
//   • PIP escalation is gated: a Support Review checklist + report must be
//     completed before "Escalate for PIP Review" becomes available.
//   • The "Escalate for PIP Review" button is the LAST step, never the first.
//   • If the staff member's gap is explained by approved leave / route
//     difficulty / funding / partner / Salesforce / overload, the PIP flag
//     is suppressed even if the raw threshold is met.

import type { CurrentUser, AppRole } from "./schools-mock";
import { ENGINE_TODAY } from "./refresh-and-followup-mock";

// ────────── Pacing + risk ──────────

export type PaceStatus = "On Track" | "Slightly Behind" | "Behind" | "High Risk" | "Critical";
export type RiskLevel = "Low" | "Medium" | "High" | "Critical";

export type TargetCategoryProgress = {
  trainingsCompleted: number;       // 0–100 (% of period target)
  validVisits: number;
  ssaCompletion: number;
  salesforceLogging: number;
  coreSchoolTargets: number;
  mscStories?: number;
  examResults?: number;
  enrollmentUpdates?: number;
};

export type SupportReviewStatus =
  | "Not Required"
  | "Required"
  | "In Progress"
  | "Support Plan Created"
  | "Report Completed"
  | "Escalated for Review";

export type StaffTargetRow = {
  staffId: string;
  staffName: string;
  initials: string;
  role: string;
  region: string;
  cluster?: string;
  supervisorId: string;

  monthlyTargetActivities: number;
  completedActivities: number;
  remainingActivities: number;
  quarterlyTargetActivities: number;
  achievementPercent: number; // 0–120
  paceStatus: PaceStatus;

  salesforceCompliancePercent: number;
  coreSchoolProgressPercent: number;
  targetCategoryProgress: TargetCategoryProgress;

  // Context that explains gaps (must be considered before any escalation)
  approvedLeaveDays: number;
  blockedPlanningDays: number;
  routeDifficultyIndex: number; // 0–100
  fundingDelayDays: number;
  unresolvedSalesforceIssues: number;
  partnerDependencyBlocks: number;
  twoConsecutiveWeekSlippage: boolean;

  // Engine-derived flags
  earlyWarningTriggered: boolean;
  earlyWarningReasons: string[];
  midYearBelow40Triggered: boolean;
  possiblePipReviewRequired: boolean;
  supportReviewStatus: SupportReviewStatus;
  recommendedSupportActions: string[];
};

// ────────── Engine ──────────

const MAJOR_CATEGORIES: (keyof TargetCategoryProgress)[] = [
  "trainingsCompleted",
  "validVisits",
  "ssaCompletion",
  "salesforceLogging",
  "coreSchoolTargets",
];

function calculatePaceStatus(achievement: number): PaceStatus {
  if (achievement >= 95) return "On Track";
  if (achievement >= 80) return "Slightly Behind";
  if (achievement >= 60) return "Behind";
  if (achievement >= 40) return "High Risk";
  return "Critical";
}

function fyMonthIndex(today: Date = ENGINE_TODAY): number {
  // FY runs October → September. Returns 1..12 with Oct = 1.
  return ((today.getMonth() - 9 + 12) % 12) + 1;
}

function isMidYearOrLater(today: Date = ENGINE_TODAY): boolean {
  return fyMonthIndex(today) >= 6; // March end / April start
}

// Early-warning: every condition is a real, named operational reason.
function detectEarlyTargetRisk(s: StaffTargetRow): {
  triggered: boolean;
  reasons: string[];
} {
  const reasons: string[] = [];
  if (s.achievementPercent < 80) reasons.push("Below 80% of expected pacing");
  if (s.targetCategoryProgress.ssaCompletion < 80) reasons.push("SSA completion behind");
  if (s.targetCategoryProgress.validVisits < 80) reasons.push("Valid visit target behind");
  if (s.targetCategoryProgress.coreSchoolTargets < 80) reasons.push("Core school support behind");
  if (s.salesforceCompliancePercent < 80) reasons.push("Salesforce logging below threshold");
  if (s.twoConsecutiveWeekSlippage) reasons.push("Two consecutive weeks of slippage");
  return { triggered: reasons.length > 0, reasons };
}

// Mid-year below-40 across ALL major categories — never one weak metric.
// Suppressed when documented context explains the gap.
export function detectMidYearBelow40(
  s: StaffTargetRow,
  today: Date = ENGINE_TODAY,
): { triggered: boolean; categoriesBelow40: string[]; suppressedReason?: string } {
  if (!isMidYearOrLater(today)) return { triggered: false, categoriesBelow40: [] };
  const allBelow40 = MAJOR_CATEGORIES.every(
    (k) => (s.targetCategoryProgress[k] ?? 0) < 40,
  );
  if (!allBelow40) return { triggered: false, categoriesBelow40: [] };
  const overallBelow = s.achievementPercent < 40;
  if (!overallBelow) return { triggered: false, categoriesBelow40: [] };

  // Context guard — explained gaps suppress the flag.
  const explained: string[] = [];
  if (s.approvedLeaveDays >= 5) explained.push(`${s.approvedLeaveDays} approved leave days`);
  if (s.blockedPlanningDays >= 5) explained.push(`${s.blockedPlanningDays} blocked planning days`);
  if (s.routeDifficultyIndex >= 75) explained.push("Unrealistic route load");
  if (s.fundingDelayDays >= 14) explained.push(`${s.fundingDelayDays}d funding delay`);
  if (s.unresolvedSalesforceIssues >= 3) explained.push("Unresolved Salesforce issues");
  if (s.partnerDependencyBlocks >= 2) explained.push("Repeated partner dependency blocks");
  if (explained.length >= 2) {
    return {
      triggered: false,
      categoriesBelow40: MAJOR_CATEGORIES.filter((k) => (s.targetCategoryProgress[k] ?? 0) < 40),
      suppressedReason: explained.join(" · "),
    };
  }
  return {
    triggered: true,
    categoriesBelow40: MAJOR_CATEGORIES.filter((k) => (s.targetCategoryProgress[k] ?? 0) < 40),
  };
}

function recommendSupportActions(s: StaffTargetRow): string[] {
  const out: string[] = [];
  if (s.routeDifficultyIndex >= 70) out.push("Adjust route plan + reduce weekly load");
  if (s.fundingDelayDays >= 7) out.push("Resolve funding delay / escalate to Accountant");
  if (s.unresolvedSalesforceIssues >= 2) out.push("Resolve Salesforce backlog with M&E");
  if (s.partnerDependencyBlocks >= 1) out.push("Assign partner support / confirm SLA");
  if (s.targetCategoryProgress.ssaCompletion < 60) out.push("Catch-up SSA plan + supervisor coaching");
  if (s.targetCategoryProgress.validVisits < 60) out.push("Group catch-up visits this period");
  if (s.approvedLeaveDays >= 5) out.push("Review target fairness given leave impact");
  if (out.length === 0) out.push("Schedule supervisor check-in + prepare 4-week catch-up plan");
  return out;
}

function annotate(s: Omit<StaffTargetRow,
  "earlyWarningTriggered" | "earlyWarningReasons" | "midYearBelow40Triggered" |
  "possiblePipReviewRequired" | "supportReviewStatus" | "recommendedSupportActions" | "paceStatus"
> & { supportReviewStatus?: SupportReviewStatus }): StaffTargetRow {
  const paceStatus = calculatePaceStatus(s.achievementPercent);
  const ew = detectEarlyTargetRisk({ ...s, paceStatus } as StaffTargetRow);
  const my = detectMidYearBelow40({ ...s, paceStatus } as StaffTargetRow);
  const recs = recommendSupportActions({ ...s, paceStatus } as StaffTargetRow);
  return {
    ...s,
    paceStatus,
    earlyWarningTriggered: ew.triggered,
    earlyWarningReasons: ew.reasons,
    midYearBelow40Triggered: my.triggered,
    possiblePipReviewRequired: my.triggered,
    supportReviewStatus: s.supportReviewStatus ?? (my.triggered ? "Required" : ew.triggered ? "Required" : "Not Required"),
    recommendedSupportActions: recs,
  };
}

// ────────── Header / KPI / attention ──────────

export const teamTargetsHeader = {
  title: "Team Targets Dashboard",
  subtitle: "Track team target progress, identify gaps, and intervene early.",
  searchPlaceholder: "Search schools, staff, plans, routes…",
  filters: { region: "All Regions", month: "May 2025" },
};

export const teamTargetsHeaderUser = {
  name: "Daniel Mwangi",
  initials: "DM",
  role: "Country Program Lead",
};

export type TeamTargetKpi = {
  key: string;
  label: string;
  value: string;
  trend: { delta: string; tone: "up" | "down" };
  icon: "target" | "calendar" | "calendarRange" | "users" | "alertTriangle" | "school" | "cloud";
  tone: "edify" | "emerald" | "amber" | "rose" | "violet";
};

export const teamTargetKpis: TeamTargetKpi[] = [
  { key: "team",       label: "Team Target Achievement",  value: "72%", trend: { delta: "8 pp vs last month",   tone: "up" },   icon: "target",        tone: "emerald" },
  { key: "monthly",    label: "Monthly Targets Achieved", value: "68%", trend: { delta: "7 pp vs Apr 2025",     tone: "up" },   icon: "calendar",      tone: "edify"   },
  { key: "quarterly",  label: "Quarterly Targets Achieved", value: "54%", trend: { delta: "5 pp vs Q1 2026",    tone: "up" },   icon: "calendarRange", tone: "amber"   },
  { key: "on_track",   label: "Staff On Track",           value: "62",  trend: { delta: "9 vs last month",      tone: "up" },   icon: "users",         tone: "edify"   },
  { key: "high_risk",  label: "High-Risk Staff",          value: "14",  trend: { delta: "3 vs last month",      tone: "up" },   icon: "alertTriangle", tone: "rose"    },
  { key: "core_track", label: "Core Schools On Track",    value: "68%", trend: { delta: "6 pp vs last month",   tone: "up" },   icon: "school",        tone: "edify"   },
  { key: "sf_compl",   label: "Salesforce Compliance",    value: "87%", trend: { delta: "5 pp vs last month",   tone: "up" },   icon: "cloud",         tone: "emerald" },
];

export type AttentionItem = {
  key: string;
  title: string;
  value: string;
  subtitle: string;
  cta: string;
  tone: "amber" | "rose" | "edify" | "violet" | "blue";
  icon: "users" | "alertTriangle" | "target" | "userCheck" | "school";
};

export const attentionItems: AttentionItem[] = [
  { key: "behind",     title: "Staff Behind Target",     value: "28",    subtitle: "Staff below 80%",                    cta: "View staff →",  tone: "amber",  icon: "users"         },
  { key: "critical",   title: "Teams at Critical Risk",  value: "6",     subtitle: "Teams < 60% achievement",            cta: "View teams →",  tone: "rose",   icon: "alertTriangle" },
  { key: "ssa_gap",    title: "SSA Target Gap",          value: "734",   subtitle: "Pending SSA activities",             cta: "View Details →", tone: "edify", icon: "target"        },
  { key: "visit_gap",  title: "Valid Visit Gap",         value: "1,248", subtitle: "Visits below target",                cta: "View Details →", tone: "violet", icon: "userCheck"   },
  { key: "core_gap",   title: "Core School Target Gap",  value: "132",   subtitle: "Core schools behind",                cta: "View schools →", tone: "blue",  icon: "school"       },
];

// ────────── Quick actions (humane — no one-click PIP) ──────────

export type QuickActionKey =
  | "Review High-Risk Staff"
  | "Rebalance Workload"
  | "View Team Targets"
  | "Approve Catch-up Plan"
  | "Check Salesforce Backlog"
  | "Open Support Review Checklist";

export type QuickAction = { key: QuickActionKey; href: string; iconKey: "alertTriangle" | "scale" | "target" | "checkCircle" | "cloud" | "shield" };

const baseQuickActions: QuickAction[] = [
  { key: "Review High-Risk Staff",   href: "/team-targets",        iconKey: "alertTriangle" },
  { key: "Rebalance Workload",       href: "/team-targets",         iconKey: "scale" },
  { key: "View Team Targets",        href: "/team-targets",     iconKey: "target" },
  { key: "Approve Catch-up Plan",    href: "/team-targets",          iconKey: "checkCircle" },
  { key: "Check Salesforce Backlog", href: "/quality-checks",        iconKey: "cloud" },
];

// Conditionally include "Open Support Review Checklist" when any staff hits
// the mid-year below-40 condition. NEVER add a "Put on PIP" action.
export function quickActionsForRows(rows: StaffTargetRow[]): QuickAction[] {
  const anyMidYearTrigger = rows.some((r) => r.midYearBelow40Triggered);
  return anyMidYearTrigger
    ? [...baseQuickActions, { key: "Open Support Review Checklist", href: "/team-targets", iconKey: "shield" }]
    : baseQuickActions;
}

// ────────── Weekly pacing + mini calendar ──────────

export const weeklyPacing = {
  weekStart: "May 12",
  weekEnd: "May 18, 2026",
  completedThisWeek: 1264,
  weeklyTarget: 1850,
  achievementPercent: 68,
  status: "Slightly Behind" as PaceStatus,
  weekday: [
    { day: "Mon", date: "12", state: "complete" as const },
    { day: "Tue", date: "13", state: "complete" as const },
    { day: "Wed", date: "14", state: "complete" as const },
    { day: "Thu", date: "15", state: "complete" as const },
    { day: "Fri", date: "16", state: "today" as const },
    { day: "Sat", date: "17", state: "future" as const },
    { day: "Sun", date: "18", state: "future" as const },
  ],
};

// ────────── Staff seed ──────────

const staffTargetPerformanceRaw: Omit<StaffTargetRow,
  "earlyWarningTriggered" | "earlyWarningReasons" | "midYearBelow40Triggered" |
  "possiblePipReviewRequired" | "supportReviewStatus" | "recommendedSupportActions" | "paceStatus"
>[] = [
  {
    staffId: "STF-GN-007", staffName: "Grace Njeri", initials: "GN", role: "CCEO",
    region: "East", supervisorId: "PL-001",
    monthlyTargetActivities: 64, completedActivities: 52, remainingActivities: 12,
    quarterlyTargetActivities: 192, achievementPercent: 81, salesforceCompliancePercent: 92, coreSchoolProgressPercent: 85,
    targetCategoryProgress: { trainingsCompleted: 88, validVisits: 84, ssaCompletion: 78, salesforceLogging: 92, coreSchoolTargets: 85 },
    approvedLeaveDays: 0, blockedPlanningDays: 3, routeDifficultyIndex: 30, fundingDelayDays: 0,
    unresolvedSalesforceIssues: 0, partnerDependencyBlocks: 0, twoConsecutiveWeekSlippage: false,
  },
  {
    staffId: "STF-JO-022", staffName: "James Otieno", initials: "JO", role: "CCEO",
    region: "Central", supervisorId: "PL-001",
    monthlyTargetActivities: 58, completedActivities: 36, remainingActivities: 22,
    quarterlyTargetActivities: 174, achievementPercent: 62, salesforceCompliancePercent: 78, coreSchoolProgressPercent: 78,
    targetCategoryProgress: { trainingsCompleted: 72, validVisits: 64, ssaCompletion: 60, salesforceLogging: 78, coreSchoolTargets: 78 },
    approvedLeaveDays: 1, blockedPlanningDays: 4, routeDifficultyIndex: 45, fundingDelayDays: 0,
    unresolvedSalesforceIssues: 1, partnerDependencyBlocks: 0, twoConsecutiveWeekSlippage: false,
  },
  {
    staffId: "STF-PM-031", staffName: "Purity Muthoni", initials: "PM", role: "CCEO",
    region: "West", supervisorId: "PL-001",
    monthlyTargetActivities: 61, completedActivities: 28, remainingActivities: 33,
    quarterlyTargetActivities: 183, achievementPercent: 46, salesforceCompliancePercent: 65, coreSchoolProgressPercent: 65,
    targetCategoryProgress: { trainingsCompleted: 56, validVisits: 50, ssaCompletion: 48, salesforceLogging: 65, coreSchoolTargets: 65 },
    approvedLeaveDays: 2, blockedPlanningDays: 5, routeDifficultyIndex: 70, fundingDelayDays: 0,
    unresolvedSalesforceIssues: 2, partnerDependencyBlocks: 1, twoConsecutiveWeekSlippage: true,
  },
  {
    staffId: "STF-AH-044", staffName: "Abdi Hassan", initials: "AH", role: "CCEO",
    region: "North", supervisorId: "PL-002",
    monthlyTargetActivities: 55, completedActivities: 18, remainingActivities: 37,
    quarterlyTargetActivities: 165, achievementPercent: 33, salesforceCompliancePercent: 54, coreSchoolProgressPercent: 54,
    targetCategoryProgress: { trainingsCompleted: 32, validVisits: 30, ssaCompletion: 28, salesforceLogging: 54, coreSchoolTargets: 54 },
    approvedLeaveDays: 6, blockedPlanningDays: 8, routeDifficultyIndex: 92, fundingDelayDays: 21,
    unresolvedSalesforceIssues: 4, partnerDependencyBlocks: 2, twoConsecutiveWeekSlippage: true,
  },
  {
    staffId: "STF-PM-052", staffName: "Peter Mutua", initials: "PM", role: "CCEO",
    region: "East", supervisorId: "PL-002",
    monthlyTargetActivities: 60, completedActivities: 21, remainingActivities: 39,
    quarterlyTargetActivities: 180, achievementPercent: 35, salesforceCompliancePercent: 47, coreSchoolProgressPercent: 47,
    targetCategoryProgress: { trainingsCompleted: 30, validVisits: 28, ssaCompletion: 32, salesforceLogging: 47, coreSchoolTargets: 47 },
    approvedLeaveDays: 0, blockedPlanningDays: 2, routeDifficultyIndex: 38, fundingDelayDays: 0,
    unresolvedSalesforceIssues: 1, partnerDependencyBlocks: 0, twoConsecutiveWeekSlippage: true,
  },
];

export const staffTargetPerformance: StaffTargetRow[] = staffTargetPerformanceRaw.map(annotate);

// ────────── Partner seed ──────────

export type PartnerCertification = "Certified" | "Pending" | "Not Certified";

export type PartnerTargetRow = {
  partnerId: string;
  partner: string;
  region: string;
  assignedActivities: number;
  completedActivities: number;
  validVisits: number;
  achievementPercent: number;
  certificationStatus: PartnerCertification;
  risk: RiskLevel;
};

export const partnerTargetPerformance: PartnerTargetRow[] = [
  { partnerId: "PRT-AHA",  partner: "Amref Health Africa",     region: "East",    assignedActivities: 520, completedActivities: 362, validVisits: 218, achievementPercent: 70, certificationStatus: "Certified",     risk: "Low"      },
  { partnerId: "PRT-WV",   partner: "World Vision",            region: "West",    assignedActivities: 480, completedActivities: 252, validVisits: 146, achievementPercent: 53, certificationStatus: "Certified",     risk: "Medium"   },
  { partnerId: "PRT-PI",   partner: "Plan International",      region: "Central", assignedActivities: 450, completedActivities: 216, validVisits: 132, achievementPercent: 48, certificationStatus: "Pending",       risk: "High"     },
  { partnerId: "PRT-STC",  partner: "Save the Children",       region: "East",    assignedActivities: 410, completedActivities: 168, validVisits: 94,  achievementPercent: 41, certificationStatus: "Certified",     risk: "High"     },
  { partnerId: "PRT-CARE", partner: "CARE International",      region: "North",   assignedActivities: 380, completedActivities: 120, validVisits: 64,  achievementPercent: 32, certificationStatus: "Not Certified", risk: "Critical" },
];

// ────────── Key target progress ──────────

export const keyTargetProgress = [
  { key: "training", label: "Trainings Completed", completed: 72,    target: 100,  pct: 72 },
  { key: "visits",   label: "Valid Visits",        completed: 1248,  target: 2000, pct: 62 },
  { key: "ssa",      label: "SSA Completion",      completed: 734,   target: 1200, pct: 61 },
  { key: "sf",       label: "Salesforce Logging",  completed: 4820,  target: 5500, pct: 88 },
  { key: "core",     label: "Core School Targets", completed: 1132,  target: 1650, pct: 69 },
];

// ────────── Distribution + regions ──────────

export const staffStatusDistribution = [
  { label: "On Track (≥ 80%)",      count: 62, pct: 43, color: "#16a34a" },
  { label: "Slightly Behind (60-79%)", count: 46, pct: 32, color: "#f59e0b" },
  { label: "High Risk (40-59%)",    count: 24, pct: 17, color: "#ef4444" },
  { label: "Critical (< 40%)",      count: 12, pct: 8,  color: "#b91c1c" },
];
export const totalStaffCount = staffStatusDistribution.reduce((a, x) => a + x.count, 0);

export const regionsBehind = [
  { region: "North",   achievementPercent: 38, tone: "rose" as const },
  { region: "East",    achievementPercent: 45, tone: "rose" as const },
  { region: "West",    achievementPercent: 52, tone: "amber" as const },
  { region: "Central", achievementPercent: 65, tone: "amber" as const },
];

// ────────── Target Recovery Focus ──────────

export type TargetRecoveryRow = {
  id: string;
  schoolOrTeam: string;
  region: string;
  ownerName: string;
  ownerInitials: string;
  gapActivities: number;
  achievementPercent: number;
  recommendedAction: string;
  deadline: string;
  riskLevel: RiskLevel;
};

export const targetRecoveryFocus: TargetRecoveryRow[] = [
  { id: "TR-1", schoolOrTeam: "Ngaremara Health Center", region: "West",    ownerName: "Purity Muthoni", ownerInitials: "PM", gapActivities: -28, achievementPercent: 42, recommendedAction: "Conduct 3 group trainings + catch-up visits",  deadline: "May 20, 2026", riskLevel: "High"     },
  { id: "TR-2", schoolOrTeam: "Dadaab Cluster",          region: "North",   ownerName: "Abdi Hassan",    ownerInitials: "AH", gapActivities: -36, achievementPercent: 34, recommendedAction: "Deploy support supervisor + rebalance workload", deadline: "May 21, 2026", riskLevel: "Critical" },
  { id: "TR-3", schoolOrTeam: "Siaya West Cluster",      region: "Central", ownerName: "James Otieno",   ownerInitials: "JO", gapActivities: -21, achievementPercent: 46, recommendedAction: "Increase partner visits + validate pending visits", deadline: "May 22, 2026", riskLevel: "High"     },
  { id: "TR-4", schoolOrTeam: "Kibwezi Sub-county",      region: "East",    ownerName: "Peter Mutua",    ownerInitials: "PM", gapActivities: -24, achievementPercent: 38, recommendedAction: "Schedule outreach + community mobilization",      deadline: "May 23, 2026", riskLevel: "High"     },
];

// ────────── Support Review Cases ──────────

export type SupportReviewCase = {
  caseId: string;
  staffId: string;
  triggeredBy: "Early Warning" | "Mid-Year Below 40%" | "Critical Target Risk";
  createdAt: string;
  createdBySystem: boolean;
  assignedProgramLeadId: string;
  workloadCapacityReview?: string;
  leaveHolidayImpactReview?: string;
  routeDifficultyReview?: string;
  schoolAccessReview?: string;
  fundingDelayReview?: string;
  partnerDependencyReview?: string;
  salesforceIssueReview?: string;
  planApprovalDelayReview?: string;
  staffContextNotes?: string;
  supervisorSupportHistory?: string;
  targetFairnessReview?: string;
  recommendedSupportActions: string[];
  supportPlanCreated: boolean;
  reviewReportCompleted: boolean;
  pipEscalationAllowed: boolean;
  status:
    | "Open"
    | "Support Review In Progress"
    | "Support Plan Active"
    | "Report Completed"
    | "Escalated"
    | "Closed";
};

export const supportReviewCases: SupportReviewCase[] = [
  {
    caseId: "SRC-1001",
    staffId: "STF-AH-044",
    triggeredBy: "Mid-Year Below 40%",
    createdAt: "2026-04-04",
    createdBySystem: true,
    assignedProgramLeadId: "PL-002",
    workloadCapacityReview: "Heavy load + 6 leave days this period.",
    leaveHolidayImpactReview: "6 approved leave days; 8 blocked planning days.",
    routeDifficultyReview: "Wajir/Mandera routes index 92 — among the toughest in country.",
    fundingDelayReview: "Funding cycle delayed 3 weeks.",
    salesforceIssueReview: "4 unresolved Salesforce issues (M&E ticket #142).",
    partnerDependencyReview: "Partner CARE not yet certified.",
    targetFairnessReview: "Targets set without route + partner factors.",
    recommendedSupportActions: [
      "Adjust route plan + reduce weekly load",
      "Resolve funding delay / escalate to Accountant",
      "Resolve Salesforce backlog with M&E",
      "Assign partner support / confirm SLA",
    ],
    supportPlanCreated: true,
    reviewReportCompleted: false,
    pipEscalationAllowed: false,
    status: "Support Review In Progress",
  },
  {
    caseId: "SRC-1002",
    staffId: "STF-PM-052",
    triggeredBy: "Mid-Year Below 40%",
    createdAt: "2026-04-04",
    createdBySystem: true,
    assignedProgramLeadId: "PL-002",
    workloadCapacityReview: "Heavy load; no blocking context recorded.",
    recommendedSupportActions: [
      "Schedule supervisor check-in + prepare 4-week catch-up plan",
      "Catch-up SSA plan + supervisor coaching",
    ],
    supportPlanCreated: false,
    reviewReportCompleted: false,
    pipEscalationAllowed: false,
    status: "Open",
  },
];

// ────────── Role-aware filters + rollups ──────────

export function filterStaffForUser(user: CurrentUser): StaffTargetRow[] {
  if (user.role === "Admin" || user.role === "CountryDirector") return staffTargetPerformance;
  if (user.role === "CountryProgramLead") return staffTargetPerformance; // demo: supervises all
  return staffTargetPerformance.filter((s) => s.staffId === user.staffId);
}

export type TeamTargetRollup = {
  totalStaff: number;
  onTrack: number;
  highRisk: number;
  critical: number;
  earlyWarnings: number;
  midYearBelow40Cases: number;
  supportReviewsInProgress: number;
};

export function teamTargetRollupFor(user: CurrentUser): TeamTargetRollup {
  const visible = filterStaffForUser(user);
  return {
    totalStaff: visible.length,
    onTrack: visible.filter((s) => s.paceStatus === "On Track" || s.paceStatus === "Slightly Behind").length,
    highRisk: visible.filter((s) => s.paceStatus === "High Risk").length,
    critical: visible.filter((s) => s.paceStatus === "Critical").length,
    earlyWarnings: visible.filter((s) => s.earlyWarningTriggered).length,
    midYearBelow40Cases: visible.filter((s) => s.midYearBelow40Triggered).length,
    supportReviewsInProgress: supportReviewCases.filter((c) => c.status === "Support Review In Progress" || c.status === "Open").length,
  };
}

// Country/RVP rollup (mock — real backend aggregates by supervisor tree)
export type CountryTargetRollup = {
  country: string;
  teamTargetAchievement: number;
  highRiskStaff: number;
  midYearBelow40: number;
  supportReportsCompleted: number;
  pipEscalationsPending: number;
};

export const countryTargetRollups: CountryTargetRollup[] = [
  { country: "Kenya",  teamTargetAchievement: 72, highRiskStaff: 14, midYearBelow40: 2, supportReportsCompleted: 1, pipEscalationsPending: 0 },
  { country: "Uganda", teamTargetAchievement: 78, highRiskStaff: 9,  midYearBelow40: 1, supportReportsCompleted: 1, pipEscalationsPending: 0 },
  { country: "Rwanda", teamTargetAchievement: 81, highRiskStaff: 6,  midYearBelow40: 0, supportReportsCompleted: 0, pipEscalationsPending: 0 },
];

// Supportive copy bank — used wherever the system flags a staff member.
export function notificationCopyFor(kind: "early-warning" | "mid-year"): string {
  if (kind === "mid-year") {
    return (
      "Mid-year support review required. This staff member is below 40% across all major target areas. " +
      "Before any Performance Improvement Plan decision, complete a support review and prepare a clear " +
      "report documenting context, support provided, and recommended next steps."
    );
  }
  return (
    "Target risk detected. This staff member is below expected pacing. Review workload, leave, route " +
    "difficulty, funding delays, Salesforce issues, and support history before deciding next steps."
  );
}

export function pipGate(c: SupportReviewCase): { allowed: boolean; reason: string } {
  if (!c.supportPlanCreated)   return { allowed: false, reason: "Create a support plan first." };
  if (!c.reviewReportCompleted) return { allowed: false, reason: "Complete the support review report first." };
  return { allowed: true, reason: "Support review report is complete." };
}

// Notification feed used by Program Lead / Country Director / RVP cards.
export type TargetNotification = {
  id: string;
  audience: AppRole[];
  kind: "early-warning" | "mid-year" | "country-risk" | "rvp-risk";
  staffName?: string;
  title: string;
  body: string;
  createdAt: string;
};

const targetNotifications: TargetNotification[] = [
  { id: "N-1", audience: ["CountryProgramLead"], kind: "early-warning", staffName: "Purity Muthoni", title: "Target risk detected — Purity Muthoni",
    body: "Below 80% pacing + two-week slippage. Review workload, route, and Salesforce backlog before next step.", createdAt: "2026-05-15" },
  { id: "N-2", audience: ["CountryProgramLead"], kind: "mid-year",      staffName: "Abdi Hassan",
    title: "Mid-year support review required — Abdi Hassan",
    body: notificationCopyFor("mid-year"), createdAt: "2026-04-04" },
  { id: "N-3", audience: ["CountryDirector"], kind: "country-risk",
    title: "2 Program Lead teams below quarterly target",
    body: "Wajir & Mandera and Eastern teams have completed support review reports awaiting your review.", createdAt: "2026-05-12" },
  { id: "N-4", audience: ["CountryDirector"], kind: "country-risk",
    title: "Mid-year below-40 cases this country: 2",
    body: "Both staff have active Support Review cases. PIP escalation gated until reports complete.", createdAt: "2026-05-12" },
];

export function notificationsForRole(role: AppRole): TargetNotification[] {
  return targetNotifications.filter((n) => n.audience.includes(role));
}
