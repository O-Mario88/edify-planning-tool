// CCEO "My Targets" Command Center engine.
//
// Contract:
//   • The CCEO homepage answers: what do I need to do this week, where do I
//     need to go, how am I progressing, where do I need help?
//   • Route map shows ONLY schools planned for the current week (not all
//     assigned schools, not the district, not high-priority lists).
//   • The current week's activities become the active todo list.
//   • Monthly budget is the aggregate of submitted activity batches — never
//     entered separately.
//   • Critical-status targets escalate to the Program Lead's view.

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";
import { regionForDistrict, type UgandaRegion } from "@/lib/uganda-districts";
import { countsTowardTarget, isFieldComplete } from "@/lib/target-counting";
import { getPaceStatus } from "@/lib/pace-status";

// ────────── Week & FY context ──────────

export const ACTIVE_FY = activeFinancialYear();

// For the demo we run from the user's clock day. Real impl reads the FY
// calendar and locks to the planned-cycle week.
export function currentMonthLabel(now: Date = new Date()): string {
  return now.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

export function currentWeekIndex(now: Date = new Date()): 1 | 2 | 3 | 4 | 5 {
  const day = now.getDate();
  if (day <= 7)  return 1;
  if (day <= 14) return 2;
  if (day <= 21) return 3;
  if (day <= 28) return 4;
  return 5;
}

// ────────── Types ──────────

export type ActivityType =
  | "School Visit"
  | "Follow-Up Visit"
  | "Core School Visit"
  | "SSA Verification"
  | "SSA Support"
  | "Training Follow-Up"
  | "Cluster Training"
  | "Cluster Meeting"
  | "Partner Visit"
  | "Special Project Visit";

export type ActivityPurpose =
  | "In-School Coaching"
  | "Training Follow-Up"
  | "Partner Follow-Up"
  | "SSA Support"
  | "SSA Verification"
  | "Core School Visit"
  | "School Improvement Visit"
  | "Special Project Visit"
  | "Data Collection";

export type ActivityStatus =
  | "Planned"
  | "Ready"
  | "In Progress"
  | "Completed"
  | "Salesforce ID Pending"
  | "Submitted for Verification"
  | "Verified"
  | "Returned"
  | "Overdue";

export type PlannedActivity = {
  id:                string;
  schoolId:          string;
  schoolName:        string;
  district:          string;
  region:            UgandaRegion | undefined;  // derived from district (UBOS)
  cluster:           string;
  lat:               number | null;       // null = missing coordinates
  lng:               number | null;
  activityType:      ActivityType;
  purpose:           ActivityPurpose;
  intervention?:     string;
  ssaScore?:         number | null;
  trainingFollowUp?: string;              // training being followed up
  week:              1 | 2 | 3 | 4 | 5;
  scheduledDay:      string;              // "Mon", "Tue" etc. for current-week
  status:            ActivityStatus;
  salesforceId?:     string;
  needsSalesforce:   boolean;
  estimatedCost:     number;
  routeGroup:        string;              // e.g. "Kitgum North · Day 1"
  priority:          "Critical" | "High" | "Medium" | "Low";
  isCore:            boolean;
};

export type TargetStatus = "On Track" | "Needs Attention" | "Critical";

export type TargetCategory = {
  key:        string;
  label:      string;
  completed:  number;
  target:     number;
  pct:        number;                     // 0-100
  expectedPct:number;                     // where the CCEO should be by now
  status:     TargetStatus;
  trend:      string;                     // e.g. "+4 vs last month"
};

export type SupportSignal = {
  id:       string;
  reason:
    | "Low completion"
    | "High overdue activities"
    | "Missing Salesforce IDs"
    | "Route difficulty"
    | "School closures"
    | "Leave / holiday impact"
    | "Budget delay"
    | "Partner dependency"
    | "No submitted plan";
  detail:   string;
  severity: "warning" | "critical";
};

// ────────── Coordinates seed ──────────
//
// Real impl reads `school.lat` / `school.lng` from the schools table. The
// demo synthesises stable lat/lng around Kitgum / Pader / Gulu so the map
// silhouette has something to draw. Two schools per dataset are left with
// null coordinates so the "missing coordinates" UX is exercised.

const DISTRICT_CENTER: Record<string, { lat: number; lng: number }> = {
  Kitgum:  { lat:  3.314, lng: 32.881 },
  Pader:   { lat:  2.802, lng: 33.027 },
  Lamwo:   { lat:  3.515, lng: 32.764 },
  Agago:   { lat:  2.825, lng: 33.382 },
  Gulu:    { lat:  2.778, lng: 32.298 },
  Omoro:   { lat:  2.605, lng: 32.523 },
};

function hashFloat(s: string, span: number): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return ((h >>> 0) % 1000 / 1000 - 0.5) * span;
}

function coords(schoolId: string, district: string): { lat: number | null; lng: number | null } {
  const c = DISTRICT_CENTER[district];
  if (!c) return { lat: null, lng: null };
  return {
    lat: +(c.lat + hashFloat(schoolId + "lat", 0.4)).toFixed(4),
    lng: +(c.lng + hashFloat(schoolId + "lng", 0.4)).toFixed(4),
  };
}

// ────────── Monthly plan (5 weeks × varying activity counts) ──────────

const SCHOOL_SEED: { id: string; name: string; district: string; cluster: string }[] = [
  { id: "SCH-101", name: "St. Peter's Primary",         district: "Kitgum",  cluster: "Kitgum North" },
  { id: "SCH-102", name: "Sunrise Junior",              district: "Kitgum",  cluster: "Kitgum Hill"  },
  { id: "SCH-103", name: "Hope Children's PS",          district: "Pader",   cluster: "Pader Central"},
  { id: "SCH-104", name: "Olive Comprehensive",         district: "Pader",   cluster: "Pader Central"},
  { id: "SCH-105", name: "Holy Rosary PS",              district: "Lamwo",   cluster: "Lamwo East"   },
  { id: "SCH-106", name: "Riverside Basic",             district: "Lamwo",   cluster: "Lamwo East"   },
  { id: "SCH-107", name: "Maple Grove Junior",          district: "Agago",   cluster: "Agago Hub"    },
  { id: "SCH-108", name: "Hilltop Comprehensive",       district: "Agago",   cluster: "Agago Hub"    },
  { id: "SCH-109", name: "Gulu Cluster Bright PS",      district: "Gulu",    cluster: "Gulu Municipality" },
  { id: "SCH-110", name: "Light of Hope Secondary",     district: "Gulu",    cluster: "Gulu Municipality" },
  { id: "SCH-111", name: "Omoro Bright Primary",        district: "Omoro",   cluster: "Omoro West"   },
  { id: "SCH-112", name: "Living Word PS",              district: "Omoro",   cluster: "Omoro West"   },
  { id: "SCH-113", name: "St. Mary's Junior",           district: "Kitgum",  cluster: "Kitgum North" },
  { id: "SCH-114", name: "Pope John PS",                district: "Pader",   cluster: "Pader Central"},
  { id: "SCH-115", name: "Lamwo Bright PS",             district: "Lamwo",   cluster: "Lamwo East"   },
  { id: "SCH-116", name: "Agago Hub Junior",            district: "Agago",   cluster: "Agago Hub"    },
  { id: "SCH-117", name: "Victory Comprehensive",       district: "Gulu",    cluster: "Gulu Municipality" },
  { id: "SCH-118", name: "Kitgum Hill Bright PS",       district: "Kitgum",  cluster: "Kitgum Hill"  },
  { id: "SCH-119", name: "Pader West Children's PS",    district: "Pader",   cluster: "Pader Central"},
  { id: "SCH-120", name: "Lamwo Friends PS",            district: "Lamwo",   cluster: "Lamwo East"   },
];

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"] as const;

const PURPOSE_BY_TYPE: Record<ActivityType, ActivityPurpose> = {
  "School Visit":          "In-School Coaching",
  "Follow-Up Visit":       "Training Follow-Up",
  "Core School Visit":     "Core School Visit",
  "SSA Verification":      "SSA Verification",
  "SSA Support":           "SSA Support",
  "Training Follow-Up":    "Training Follow-Up",
  "Cluster Training":      "School Improvement Visit",
  "Cluster Meeting":       "School Improvement Visit",
  "Partner Visit":         "Partner Follow-Up",
  "Special Project Visit": "Special Project Visit",
};

// The mock plan represents 28 activities across 4-5 weeks with mixed
// completion state. Week 2 is the active week so it has the richest detail.

function makeActivity(
  i: number,
  schoolIdx: number,
  type: ActivityType,
  week: 1 | 2 | 3 | 4 | 5,
  status: ActivityStatus,
  dayIdx: number = i % 5,
): PlannedActivity {
  const s = SCHOOL_SEED[schoolIdx % SCHOOL_SEED.length];
  // Two intentionally-missing-coord schools so the demo can show the
  // "missing coordinates" UX.
  const missing = schoolIdx === 11 || schoolIdx === 18;
  const c = missing ? { lat: null, lng: null } : coords(s.id, s.district);
  const isCore = type === "Core School Visit";
  const needsSf = status === "Completed" || status === "Salesforce ID Pending" || status === "Submitted for Verification";
  // SV- for visits, TS- for trainings + cluster meetings (logged in
  // Salesforce as trainings). Only Verified / Submitted activities carry a
  // captured ID; everything earlier is still awaiting the SF ID.
  const sfPrefix = type === "Cluster Training" || type === "Cluster Meeting" ? "TS-" : "SV-";
  const sfId = status === "Verified" || status === "Submitted for Verification"
    ? `${sfPrefix}${String(1200 + i * 7).padStart(5, "0")}`
    : undefined;
  return {
    id:                `ACT-${String(i + 1).padStart(3, "0")}`,
    region:            regionForDistrict(s.district),
    schoolId:          s.id,
    schoolName:        s.name,
    district:          s.district,
    cluster:           s.cluster,
    lat:               c.lat,
    lng:               c.lng,
    activityType:      type,
    purpose:           PURPOSE_BY_TYPE[type],
    intervention:      type === "Training Follow-Up" ? "Leadership Best Practice"
                     : type === "Follow-Up Visit"    ? "Teaching Environment"
                     : type === "School Visit"       ? "Christ-like Behavior"
                     : undefined,
    ssaScore:          isCore ? 5.6 : (i % 4 === 0 ? null : +(4.8 + (i % 30) / 10).toFixed(1)),
    trainingFollowUp:  type === "Training Follow-Up" ? `Leadership Best Practice — Apr ${(i % 27) + 1}` : undefined,
    week,
    scheduledDay:      DAY_NAMES[dayIdx % 5],
    status,
    salesforceId:      sfId,
    needsSalesforce:   needsSf,
    estimatedCost:     type === "Cluster Training"    ? 2_400_000
                     : type === "Cluster Meeting"     ?   480_000
                     : type === "Partner Visit"       ?   120_000
                     : type === "Core School Visit"   ?   110_000
                     : type === "Training Follow-Up"  ?   105_000
                     : type === "SSA Verification"    ?    65_000
                     :                                     95_000,
    routeGroup:        `${s.cluster} · ${type === "Cluster Training" || type === "Cluster Meeting" ? "Hub" : `Day ${dayIdx + 1}`}`,
    priority:          status === "Overdue" ? "Critical"
                     : isCore ? "High"
                     : (i % 5 === 0 ? "High" : i % 7 === 0 ? "Critical" : "Medium"),
    isCore,
  };
}

// 28 activities seeded by hand to mix activity types + statuses across 4
// weeks. Week 2 is the active week for the demo.
export const plannedActivities: PlannedActivity[] = [
  // Week 1 — mostly Completed / Verified
  makeActivity( 0,  0, "School Visit",         1, "Verified", 0),
  makeActivity( 1,  1, "School Visit",         1, "Verified", 1),
  makeActivity( 2,  2, "Follow-Up Visit",      1, "Verified", 2),
  makeActivity( 3,  3, "Core School Visit",    1, "Verified", 3),
  makeActivity( 4,  4, "SSA Verification",     1, "Submitted for Verification", 4),
  makeActivity( 5,  5, "Cluster Training",     1, "Verified", 2),

  // Week 2 — CURRENT — Planned / In Progress / Overdue / Completed
  makeActivity( 6,  6, "School Visit",         2, "Planned",      0),
  makeActivity( 7,  7, "School Visit",         2, "Planned",      0),
  makeActivity( 8,  8, "Follow-Up Visit",      2, "In Progress",  1),
  makeActivity( 9,  9, "Core School Visit",    2, "Planned",      1),
  makeActivity(10, 10, "Training Follow-Up",   2, "Planned",      2),
  makeActivity(11, 11, "School Visit",         2, "Overdue",      2),     // missing coords
  makeActivity(12, 12, "SSA Support",          2, "Planned",      3),
  makeActivity(13, 13, "Cluster Meeting",      2, "Ready",        3),
  makeActivity(14, 14, "Partner Visit",        2, "Planned",      4),
  makeActivity(15, 15, "School Visit",         2, "Salesforce ID Pending", 4),
  makeActivity(16, 16, "School Visit",         2, "Completed",    0),

  // Week 3 — Planned, future
  makeActivity(17, 17, "School Visit",         3, "Planned", 0),
  makeActivity(18, 18, "Follow-Up Visit",      3, "Planned", 1),  // missing coords
  makeActivity(19, 19, "Core School Visit",    3, "Planned", 2),
  makeActivity(20,  0, "Cluster Training",     3, "Planned", 2),
  makeActivity(21,  1, "Training Follow-Up",   3, "Planned", 3),
  makeActivity(22,  2, "Special Project Visit",3, "Planned", 4),

  // Week 4 — Planned, future
  makeActivity(23,  3, "School Visit",         4, "Planned", 0),
  makeActivity(24,  4, "SSA Support",          4, "Planned", 1),
  makeActivity(25,  5, "Cluster Meeting",      4, "Planned", 2),
  makeActivity(26,  6, "Partner Visit",        4, "Planned", 3),
  makeActivity(27,  7, "School Visit",         4, "Planned", 4),
];

// ────────── Selectors ──────────

export function activitiesForWeek(week: 1 | 2 | 3 | 4 | 5): PlannedActivity[] {
  return plannedActivities.filter((a) => a.week === week);
}

export function thisWeekActivities(): PlannedActivity[] {
  return activitiesForWeek(currentWeekIndex());
}

export function thisWeekSchoolsWithCoords(): PlannedActivity[] {
  return thisWeekActivities().filter((a) => a.lat != null && a.lng != null);
}

export function thisWeekMissingCoords(): PlannedActivity[] {
  return thisWeekActivities().filter((a) => a.lat == null || a.lng == null);
}

// ────────── Monthly KPI summary ──────────

export type MonthlyKpis = {
  monthLabel:           string;
  monthlyAchievementPct:number;
  plannedCount:         number;
  completedCount:       number;
  verifiedCount:        number;
  pendingSalesforceCount:number;
  overdueCount:         number;
  budgetRequestedUgx:   number;
  thisWeekTodoCount:    number;
  thisWeekProgressPct:  number;
};

export function monthlyKpis(now: Date = new Date()): MonthlyKpis {
  const planned   = plannedActivities.length;
  // Achievement / target progress = IA-verified only (canonical rule).
  // Submitted/Completed/SF-pending are *progress signals* — not target
  // completion — so they no longer inflate the monthly achievement %.
  const verified  = plannedActivities.filter(countsTowardTarget).length;
  // Keep the legacy "field-complete" count for the weekly progress chip
  // — the field's view of "done today" before IA closes the loop.
  const fieldDone = plannedActivities.filter(isFieldComplete).length;
  const pendingSf = plannedActivities.filter((a) => a.status === "Salesforce ID Pending" || a.status === "Submitted for Verification").length;
  const overdue   = plannedActivities.filter((a) => a.status === "Overdue").length;
  // Budget Requested — only count batches that have been pushed past
  // Planned/Draft. Pure-planned activities aren't a real budget request.
  // TODO: When PlanBuilder's submitted batches feed the engine directly,
  // source from `localStorage['planBuilder.submittedBatches']` totals only.
  const budget    = plannedActivities
    .filter((a) =>
      a.status === "Ready" ||
      a.status === "In Progress" ||
      a.status === "Completed" ||
      a.status === "Salesforce ID Pending" ||
      a.status === "Submitted for Verification" ||
      a.status === "Verified")
    .reduce((a, b) => a + b.estimatedCost, 0);
  const week      = thisWeekActivities();
  const weekDone  = week.filter(isFieldComplete).length;
  return {
    monthLabel:            currentMonthLabel(now),
    // monthlyAchievementPct uses VERIFIED / planned — the canonical
    // target rule. Field-complete counts feed `completedCount` so the
    // UI still has a "how many got done in the field" number to show.
    monthlyAchievementPct: planned === 0 ? 0 : Math.round((verified / planned) * 100),
    plannedCount:          planned,
    completedCount:        fieldDone,
    verifiedCount:         verified,
    pendingSalesforceCount:pendingSf,
    overdueCount:          overdue,
    budgetRequestedUgx:    budget,
    thisWeekTodoCount:     week.length,
    thisWeekProgressPct:   week.length === 0 ? 0 : Math.round((weekDone / week.length) * 100),
  };
}

// ────────── Weekly breakdown ──────────

export type WeekBreakdown = {
  week:            1 | 2 | 3 | 4 | 5;
  isCurrent:       boolean;
  totalActivities: number;
  byType:          Record<ActivityType, number>;
  estimatedCost:   number;
  completed:       number;
};

export function weeklyBreakdown(now: Date = new Date()): WeekBreakdown[] {
  const out: WeekBreakdown[] = [];
  const curr = currentWeekIndex(now);
  for (const w of [1, 2, 3, 4] as const) {
    const rows = activitiesForWeek(w);
    const byType = {} as Record<ActivityType, number>;
    for (const r of rows) byType[r.activityType] = (byType[r.activityType] ?? 0) + 1;
    out.push({
      week:            w,
      isCurrent:       w === curr,
      totalActivities: rows.length,
      byType,
      estimatedCost:   rows.reduce((a, b) => a + b.estimatedCost, 0),
      // "completed" on the weekly card represents target progress — only
      // verified visits count. Field-complete-but-unverified work shows
      // up via the pending Salesforce + this-week progress chips.
      completed:       rows.filter(countsTowardTarget).length,
    });
  }
  return out;
}

// ────────── Target categories with progress + status ──────────

const TARGET_DEFINITIONS: { key: string; label: string; target: number; match: (a: PlannedActivity) => boolean }[] = [
  { key: "school_visits",         label: "School Visits",          target: 20, match: (a) => a.activityType === "School Visit" },
  { key: "ssa_completion",        label: "SSA Completion",         target: 4,  match: (a) => a.activityType === "SSA Verification" || a.activityType === "SSA Support" },
  { key: "training_follow_ups",   label: "Training Follow-Ups",    target: 6,  match: (a) => a.activityType === "Training Follow-Up" || a.activityType === "Follow-Up Visit" },
  { key: "cluster_trainings",     label: "Cluster Trainings",      target: 2,  match: (a) => a.activityType === "Cluster Training" },
  { key: "cluster_meetings",      label: "Cluster Meetings",       target: 2,  match: (a) => a.activityType === "Cluster Meeting" },
  { key: "core_visits",           label: "Core School Visits",     target: 3,  match: (a) => a.activityType === "Core School Visit" },
  { key: "partner_follow_ups",    label: "Partner Follow-Ups",     target: 4,  match: (a) => a.activityType === "Partner Visit" },
  { key: "special_project",       label: "Special Project Visits", target: 1,  match: (a) => a.activityType === "Special Project Visit" },
];

// Local helper kept for backward compatibility — forwards to the
// canonical `getPaceStatus` so every pace decision goes through the
// same thresholds. Inputs are converted: pct/expected become a
// pseudo-completed / target ratio that exercises the canonical
// 0.95 / 0.80 cutoffs.
function statusFromGap(pct: number, expected: number): TargetStatus {
  return getPaceStatus({
    completed:     pct,
    target:        100,
    expectedByNow: Math.max(1, expected),
  });
}

export function targetCategories(now: Date = new Date()): TargetCategory[] {
  // Expected % = (currentWeek / total weeks in month) × 100 (cap at 95).
  const expected = Math.min(95, currentWeekIndex(now) * 25);
  const out: TargetCategory[] = [];
  for (const def of TARGET_DEFINITIONS) {
    const matches = plannedActivities.filter(def.match);
    // Only IA-verified activities count toward target completion —
    // canonical rule from `target-counting.countsTowardTarget`.
    const completed = matches.filter(countsTowardTarget).length;
    const pct = def.target === 0 ? 0 : Math.min(100, Math.round((completed / def.target) * 100));
    out.push({
      key:         def.key,
      label:       def.label,
      completed,
      target:      def.target,
      pct,
      expectedPct: expected,
      status:      statusFromGap(pct, expected),
      trend:       completed > 0 ? `+${completed} this month` : "Not started",
    });
  }
  // Two compliance bars based on overall plan state
  const total       = plannedActivities.length;
  const sfCompliant = plannedActivities.filter((a) => a.status === "Verified" || a.status === "Submitted for Verification" || !a.needsSalesforce).length;
  const sfPct       = total === 0 ? 0 : Math.round((sfCompliant / total) * 100);
  out.push({
    key:         "sf_compliance",
    label:       "Salesforce Compliance",
    completed:   sfCompliant,
    target:      total,
    pct:         sfPct,
    expectedPct: 95,
    status:      sfPct >= 95 ? "On Track" : sfPct >= 80 ? "Needs Attention" : "Critical",
    trend:       `${sfPct}% of planned activities`,
  });
  const evCompliant = plannedActivities.filter((a) => a.status === "Verified" || a.status === "Submitted for Verification").length;
  const evPct       = total === 0 ? 0 : Math.round((evCompliant / total) * 100);
  out.push({
    key:         "evidence_submitted",
    label:       "Evidence Submitted",
    completed:   evCompliant,
    target:      total,
    pct:         evPct,
    expectedPct: expected,
    status:      statusFromGap(evPct, expected),
    trend:       `${evCompliant}/${total} batches with evidence`,
  });
  return out;
}

// ────────── Support signals ──────────

export function supportSignals(now: Date = new Date()): SupportSignal[] {
  const out: SupportSignal[] = [];
  const overdue = plannedActivities.filter((a) => a.status === "Overdue");
  if (overdue.length > 0) {
    out.push({
      id:       "overdue",
      reason:   "High overdue activities",
      detail:   `${overdue.length} activity${overdue.length === 1 ? "" : "s"} overdue this month — supervisor review recommended.`,
      severity: overdue.length >= 3 ? "critical" : "warning",
    });
  }
  const missingCoord = thisWeekMissingCoords();
  if (missingCoord.length > 0) {
    out.push({
      id:       "route-difficulty",
      reason:   "Route difficulty",
      detail:   `${missingCoord.length} school${missingCoord.length === 1 ? "" : "s"} this week without coordinates — route quality cannot be fully calculated.`,
      severity: "warning",
    });
  }
  const pendingSf = plannedActivities.filter((a) => a.status === "Salesforce ID Pending");
  if (pendingSf.length >= 3) {
    out.push({
      id:       "sf-missing",
      reason:   "Missing Salesforce IDs",
      detail:   `${pendingSf.length} completed activities are waiting on Salesforce IDs.`,
      severity: "warning",
    });
  }
  const cats = targetCategories(now);
  const critical = cats.filter((c) => c.status === "Critical");
  if (critical.length >= 2) {
    out.push({
      id:       "low-completion",
      reason:   "Low completion",
      detail:   `${critical.length} target categories are critically behind the expected ${cats[0]?.expectedPct ?? 0}% pace.`,
      severity: "critical",
    });
  }
  return out;
}

export function supervisorInterventionNeeded(now: Date = new Date()): boolean {
  return supportSignals(now).some((s) => s.severity === "critical");
}

// ────────── Route preview for this week ──────────

export type RouteFeasibility =
  | "Good Route"
  | "Manageable"
  | "Heavy Travel"
  | "Unrealistic"
  | "Missing Coordinates";

export type WeekRoutePreview = {
  week:                  1 | 2 | 3 | 4 | 5;
  totalSchools:          number;
  schoolsWithCoords:     number;
  missingCoordsCount:    number;
  suggestedRouteGroups:  number;
  estimatedTravelDays:   number;
  feasibility:           RouteFeasibility;
  schools:               PlannedActivity[];
  missingCoordsSchools:  PlannedActivity[];
};

export function thisWeekRoutePreview(now: Date = new Date()): WeekRoutePreview {
  const week = currentWeekIndex(now);
  const activities = activitiesForWeek(week);
  const withCoords = activities.filter((a) => a.lat != null && a.lng != null);
  const missing    = activities.filter((a) => a.lat == null || a.lng == null);
  const groups     = new Set(activities.map((a) => a.routeGroup));
  const feasibility: RouteFeasibility =
    missing.length > 0 && missing.length / Math.max(1, activities.length) > 0.3 ? "Missing Coordinates"
  : activities.length <= 12 ? "Good Route"
  : activities.length <= 16 ? "Manageable"
  : activities.length <= 22 ? "Heavy Travel"
  :                            "Unrealistic";
  return {
    week,
    totalSchools:         activities.length,
    schoolsWithCoords:    withCoords.length,
    missingCoordsCount:   missing.length,
    suggestedRouteGroups: groups.size,
    estimatedTravelDays:  Math.min(5, Math.ceil(activities.length / 5)),
    feasibility,
    schools:              activities,
    missingCoordsSchools: missing,
  };
}
