// Mobile (CCEO Field Work) — composes data from existing desktop mocks so
// the mobile and desktop dashboards never drift. Each export below has a
// "// Desktop counterpart:" pointer telling readers where the same value
// flows on the web console.

import { partnerDelivery } from "./special-projects-mock";
import { priorityDirectorSchools } from "./director-mock";
import { ssaInterventionFullName } from "./director-mock";
import type { EdifyRole } from "@/lib/auth-public";
import {
  computeVisitCost,
  computeTrainingCost,
  computeClusterMeetingCost,
} from "@/lib/cost-engine/cost-engine";
import {
  DEFAULT_VISIT_RATES,
  DEFAULT_GROUP_RATES,
} from "@/lib/cost-engine/cost-rates-default";

void partnerDelivery; void priorityDirectorSchools; void ssaInterventionFullName;

// ────────── Identity ──────────

export const mobileUser = {
  name: "Sarah Okello",
  firstName: "Sarah",
  initials: "SO",
  greeting: "Good morning",
  notificationCount: 12,
  district: "Kitgum",
};

// ────────── Screen 1 · Monthly Dashboard Home ──────────
//
// Desktop counterpart: /dashboards/cpl (Country Program Lead) — same KPIs,
// scoped to the signed-in CCEO instead of the country.

export const homeHero = {
  title: "You are changing schools every week.",
  subtitle: "Your leadership today builds a brighter tomorrow.",
};

export const monthSelector = {
  label: "May 2025",
  hint: "This Month",
};

export type MetricTile = {
  key: string;
  label: string;
  value: string;
  trend: { delta: string; tone: "up" | "down" };
  spark: { seed: number; trend: "up" | "down" };
};

export const monthlyPerformance: MetricTile[] = [
  { key: "planned",   label: "Planned Activities", value: "132", trend: { delta: "18%", tone: "up" }, spark: { seed: 11, trend: "up" } },
  { key: "completed", label: "Completed",          value: "14",  trend: { delta: "27%", tone: "up" }, spark: { seed: 12, trend: "up" } },
  { key: "awaiting",  label: "Awaiting Salesforce ID", value: "11", trend: { delta: "8%", tone: "up" }, spark: { seed: 13, trend: "up" } },
  { key: "target",    label: "Monthly Target Progress", value: "81%", trend: { delta: "9%", tone: "up" }, spark: { seed: 14, trend: "up" } },
];

export const schoolStats = [
  { key: "active",    label: "Active Schools",   value: "78", trend: { delta: "15%", tone: "up" as const }, spark: { seed: 21, trend: "up" as const } },
  { key: "priority",  label: "Priority Schools", value: "34", trend: { delta: "7%",  tone: "up" as const }, spark: { seed: 22, trend: "up" as const } },
];

export const thisWeekStats = {
  weekLabel: "Week 3",
  tiles: [
    { key: "cluster_trainings", label: "Cluster Trainings",  value: 0,  total: 0, status: "scheduled" as const },
    { key: "in_school",         label: "In-School Activities", value: 0, total: 0, status: "scheduled" as const },
    { key: "school_visits",     label: "School Visits Planned", value: 0, total: 0, status: "scheduled" as const },
  ],
};

export type PriorityAttention = {
  key: string;
  label: string;
  count: number;
  tone: "rose" | "amber" | "violet" | "blue";
  icon: "alertTriangle" | "mapPinOff" | "graduationCapOff" | "shieldOff";
};

export const priorityAttention: PriorityAttention[] = [
  { key: "low_ssa",    label: "Low SSA Performance",         count: 16, tone: "rose",   icon: "alertTriangle" },
  { key: "no_visit",   label: "No Visit",                    count: 9,  tone: "amber",  icon: "mapPinOff" },
  { key: "no_training", label: "No Training",                count: 7,  tone: "violet", icon: "graduationCapOff" },
  { key: "neither",    label: "Neither Training nor Visit",  count: 2,  tone: "blue",   icon: "shieldOff" },
];

export type QuickAction = {
  key: string;
  label: string;
  href: string;
  icon: "plan" | "route" | "logVisit" | "data";
};

export const homeQuickActions: QuickAction[] = [
  { key: "plan",      label: "Plan This Week",  href: "/my-plan",  icon: "plan" },
  { key: "route",     label: "Smart Route",     href: "/route", icon: "route" },
  { key: "log",       label: "Log Visit",       href: "/queue", icon: "logVisit" },
  { key: "cluster",   label: "Add Cluster Data", href: "/my-plan", icon: "data" },
];

// ────────── Screen 2 · Monthly Plan / Todo ──────────
//
// Desktop counterpart: /planning — Edify Planning Tool. Same activity
// objects; mobile shows them grouped by week instead of by cluster.

export const monthSummary = {
  weekStart: "May 12 – May 18",
  totals: [
    { key: "cluster_trainings", label: "Cluster Trainings",   value: 4   },
    { key: "cluster_meetings",  label: "Cluster Meetings",    value: 2   },
    { key: "school_visits",     label: "School Visits by Me", value: 18  },
    { key: "partner_followups", label: "Partner Follow-ups",  value: 5   },
  ],
  monthFooters: [
    { key: "month_planned", label: "Planned Activities for Month", value: "32"   },
    { key: "month_cost",    label: "Total Cost for Month",         value: "UGX 970K" },
  ],
  weekSummary: { plannedActivities: 20, totalCost: "UGX 260K" },
};

export const planWeeks = [
  { week: 1, range: "Apr 30 – May 4", current: false },
  { week: 2, range: "May 5 – 11",     current: false },
  { week: 3, range: "May 12 – 18",    current: true  },
  { week: 4, range: "May 19 – 25",    current: false },
  { week: 5, range: "May 26 – Jun 1", current: false },
];

export type PlanFilter = "all" | "cluster" | "in_school" | "follow_up";
export type PlanItemStatus = "Planned" | "In Progress" | "Verified" | "Awaiting SF ID";
export type PlanItemType = "Cluster Training" | "Cluster Meeting" | "Visit" | "Follow-Up Visit";

/**
 * One entry per time a planned activity has been moved. Append-only —
 * the same audit-trail pattern as cluster meetings, applied to every
 * visit, follow-up, training, and in-school activity. The reschedule
 * modal renders the history so the next person who touches the
 * schedule sees how stable (or not) the slot has been.
 */
export type PlanItemReschedule = {
  from:    string;   // previous date ("May 14, 2025")
  to:      string;   // new date
  reason:  string;   // one of ACTIVITY_RESCHEDULE_REASONS or free text
  movedBy: string;   // person who initiated the move
  movedAt: string;   // timestamp the move was logged
};

/** Canonical reasons offered in the activity-reschedule modal. */
export const ACTIVITY_RESCHEDULE_REASONS = [
  "School closed / public holiday",
  "Head teacher unavailable",
  "Weather / road impassable",
  "Staff / partner unable to travel",
  "Activity prerequisite not ready (e.g. SSA)",
  "Conflicting cluster meeting",
  "Security / safety concern",
  "Other",
] as const;

export type PlanItem = {
  id: string;
  type: PlanItemType;
  title: string;
  context: string;
  date: string;
  weekLabel: string;
  filter: PlanFilter;
  status: PlanItemStatus;
  /** Whoever set the date — defaults to "Field staff" if not specified. */
  proposedBy?: string;
  /** Append-only history of moves on this slot. Drives the badge + history list. */
  reschedules?: PlanItemReschedule[];
  /**
   * CD-driven cost calculation inputs. When present, the schedule's
   * cost breakdown is computed by lib/cost-engine instead of the flat
   * PLAN_ITEM_COST_UGX fallback. This is what makes a plan's cost
   * line-itemised (transport / lunch / accommodation / etc.) and
   * gives the approval routing a real Safe / Needs Review / Blocked
   * verdict instead of a rounded number.
   *
   * Items without context fall back to the flat rate so legacy mock
   * data and any future shorthand entries still render a sensible
   * total.
   */
  activityContext?: PlanItemActivityContext;
};

/**
 * What the cost engine needs to compute a full breakdown for one
 * planned activity. Modelled to match the CCEO/PL gateway questions:
 *   • Activity type — derived from item.type
 *   • Who delivers — `mode` ("staff" | "partner")
 *   • District type — "primary" | "secondary" (resolved from the
 *     staff's home district vs the school's district)
 *   • Number of schools / days / nights — for visits
 *   • Participants — for trainings and cluster meetings
 */
export type PlanItemActivityContext = {
  mode:          "staff" | "partner";
  districtType?: "primary" | "secondary";  // visits only
  schools?:      number;                    // visits only — default 1
  days?:         number;                    // visits only — default 1
  nights?:       number;                    // visits only — default derived
  participants?: number;                    // training / cluster meeting only
};

// Per-activity fund need (UGX) — what disburses for a single planned
// item. Production reads from country cost-settings; these defaults
// keep monthly totals aligned with the existing weekly summary
// numbers (~22k average across mixed activity types). The plan-item
// estimate is the user's view of "what funds I need released"; the
// authoritative budget calculation still lives in plan-builder-engine
// (per-cluster training cost includes facilitator + venue + materials).
export const PLAN_ITEM_COST_UGX: Record<PlanItemType, number> = {
  "Visit":            25_000,
  "Follow-Up Visit":  25_000,
  "Cluster Training": 50_000,
  "Cluster Meeting":  18_000,
};

/** Returns the UGX disbursement need for one planned activity.
 *  Delegates to lib/cost-engine when activityContext is present;
 *  otherwise falls back to the flat-rate PLAN_ITEM_COST_UGX so legacy
 *  mock entries without context still render a sensible total. */
export function estimatedCostFor(item: PlanItem): number {
  if (item.activityContext) {
    return computeItemTotalUgx(item);
  }
  return PLAN_ITEM_COST_UGX[item.type];
}

// Computes the full breakdown via cost-engine. Co-located here so
// callers can share the result instead of recomputing per render.
function computeItemTotalUgx(item: PlanItem): number {
  const breakdown = engineBreakdownFor(item);
  return breakdown?.total ?? PLAN_ITEM_COST_UGX[item.type];
}

/**
 * Computes the engine breakdown for a plan item. Returns the
 * canonical CostBreakdown / GroupCostBreakdown shape from the engine,
 * or `null` when activityContext is missing (caller falls back to the
 * flat CostLine list above).
 *
 * Lifted to module scope so the schedule's UI helpers can call it
 * once per row instead of inlining the engine plumbing.
 */
export function engineBreakdownFor(item: PlanItem):
  | { kind: "visit"; total: number; lines: CostLine[]; missingRates: string[]; districtType: "primary" | "secondary"; participants?: number; nights?: number }
  | { kind: "training"; total: number; lines: CostLine[]; missingRates: string[]; participants: number }
  | { kind: "cluster-meeting"; total: number; lines: CostLine[]; missingRates: string[]; participants: number }
  | null
{
  const ctx = item.activityContext;
  if (!ctx) return null;

  if (item.type === "Cluster Training") {
    const result = computeTrainingCost({
      participants: ctx.participants ?? 0,
      rates:        DEFAULT_GROUP_RATES,
    });
    return {
      kind:          "training",
      total:         result.totalUgx,
      lines:         result.lines.map(toFlatLine),
      missingRates:  result.missingRates,
      participants:  result.participants,
    };
  }

  if (item.type === "Cluster Meeting") {
    const result = computeClusterMeetingCost({
      participants: ctx.participants ?? 0,
      rates:        DEFAULT_GROUP_RATES,
    });
    return {
      kind:          "cluster-meeting",
      total:         result.totalUgx,
      lines:         result.lines.map(toFlatLine),
      missingRates:  result.missingRates,
      participants:  result.participants,
    };
  }

  // Visit or Follow-Up Visit
  const schoolCount = ctx.schools ?? 1;
  const district    = ctx.districtType ?? "primary";
  const result = computeVisitCost({
    mode:    ctx.mode,
    days:    ctx.days,
    nights:  ctx.nights,
    schools: Array.from({ length: schoolCount }, (_, i) => ({
      schoolId:    `${item.id}-stop-${i + 1}`,
      schoolName:  item.context,
      districtType: district,
    })),
    rates: DEFAULT_VISIT_RATES,
  });
  return {
    kind:          "visit",
    total:         result.totalUgx,
    lines:         result.lines.map(toFlatLine),
    missingRates:  result.missingRates,
    districtType:  result.tripDistrictType,
    nights:        result.nights,
  };
}

// Map engine CostLine → the flat CostLine shape ActivityDetail
// already renders. Same field names; the cast keeps the call site
// short and lets the engine evolve its own type independently.
function toFlatLine(line: { label: string; amountUgx: number }): CostLine {
  return { label: line.label, amount: line.amountUgx };
}

// Cost line items per activity type. Sums to PLAN_ITEM_COST_UGX[type]
// so the planning view, the disbursement queue, and the audit trail
// all roll up to the same total. Production reads category breakdowns
// from cost-settings (transport rates per district, per-diem bands,
// venue/facilitator catalogues).

export type CostLine = { label: string; amount: number };

const COST_LINES_BY_TYPE: Record<PlanItemType, CostLine[]> = {
  "Visit": [
    { label: "Transport (round trip)", amount: 10_000 },
    { label: "Per diem",                amount: 12_000 },
    { label: "Materials + handouts",    amount:  3_000 },
  ],
  "Follow-Up Visit": [
    { label: "Transport (round trip)", amount: 10_000 },
    { label: "Per diem",                amount: 12_000 },
    { label: "Evidence + verification", amount:  3_000 },
  ],
  "Cluster Training": [
    { label: "Venue",                  amount: 15_000 },
    { label: "Facilitator stipend",    amount: 20_000 },
    { label: "Materials + handouts",   amount: 10_000 },
    { label: "Refreshments",           amount:  5_000 },
  ],
  "Cluster Meeting": [
    { label: "Venue",                  amount:  8_000 },
    { label: "Refreshments",           amount: 10_000 },
  ],
};

/** Returns the cost line items that sum to estimatedCostFor(item).
 *  Engine-driven when activityContext is present (line items reflect
 *  the actual CD-set rates and the district-type rules); otherwise
 *  falls back to the flat per-type breakdown. */
export function costBreakdownFor(item: PlanItem): CostLine[] {
  const breakdown = engineBreakdownFor(item);
  if (breakdown) return breakdown.lines;
  return COST_LINES_BY_TYPE[item.type];
}

export const planItems: PlanItem[] = [
  // Week 2 — May 5-9: completed/in-flight from earlier in the month.
  { id: "p-w2-1", type: "Visit",            title: "Visit",             context: "Acholi Beach PS",        date: "May 5, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  { id: "p-w2-2", type: "Visit",            title: "Visit",             context: "Bright Star Academy",    date: "May 6, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  { id: "p-w2-3", type: "Cluster Meeting",  title: "Cluster Meeting",   context: "Kitgum North Cluster",   date: "May 7, 2025",  weekLabel: "Week 2", filter: "cluster",   status: "Verified" },
  { id: "p-w2-4", type: "Follow-Up Visit",  title: "Follow-Up Visit",   context: "Sunrise PS",             date: "May 8, 2025",  weekLabel: "Week 2", filter: "follow_up", status: "Verified" },
  { id: "p-w2-5", type: "Visit",            title: "Visit",             context: "Hilltop School",         date: "May 9, 2025",  weekLabel: "Week 2", filter: "in_school", status: "In Progress" },
  // Week 3 — May 12-16: current week, mixed status.
  { id: "p-1", type: "Cluster Training",    title: "Cluster Training",  context: "Kitgum Central",         date: "May 12, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned",
    proposedBy: "Sarah Nanyongo (CCEO)",
    reschedules: [
      { from: "Apr 28, 2025", to: "May 5, 2025",  reason: "Weather / road impassable",         movedBy: "Sarah Nanyongo (CCEO)",         movedAt: "Apr 26, 2025 16:05" },
      { from: "May 5, 2025",  to: "May 12, 2025", reason: "Conflicting cluster meeting",       movedBy: "Sarah Nanyongo (CCEO)",         movedAt: "May 2, 2025 09:42" },
    ],
  },
  { id: "p-2", type: "Cluster Meeting",     title: "Cluster Meeting",   context: "Orom Cluster",           date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned",
    // 40-participant cluster meeting — 10k × participants.
    activityContext: { mode: "staff", participants: 40 },
  },
  { id: "p-3", type: "Visit",               title: "Visit",             context: "Pope John PS",           date: "May 12, 2025", weekLabel: "Week 3", filter: "in_school", status: "In Progress",
    // Primary-district staff visit, 1 school 1 day — transport + lunch only.
    activityContext: { mode: "staff", districtType: "primary", schools: 1, days: 1 },
  },
  { id: "p-4", type: "Visit",               title: "Visit",             context: "St. Peter Primary",      date: "May 13, 2025", weekLabel: "Week 3", filter: "in_school", status: "In Progress",
    // Secondary-district staff visit, 1 school 1 day 1 night — full overnight breakdown.
    activityContext: { mode: "staff", districtType: "secondary", schools: 1, days: 1, nights: 1 },
  },
  { id: "p-5", type: "Follow-Up Visit",     title: "Follow-Up Visit",   context: "Nigina UMEA",            date: "May 14, 2025", weekLabel: "Week 3", filter: "follow_up", status: "Awaiting SF ID",
    proposedBy: "Daniel Mwangi (Field Officer)",
    reschedules: [
      { from: "May 7, 2025",  to: "May 14, 2025", reason: "Head teacher unavailable",         movedBy: "Daniel Mwangi (Field Officer)", movedAt: "May 5, 2025 11:20" },
    ],
  },
  { id: "p-6", type: "Cluster Training",    title: "Cluster Training",  context: "Pakele Cluster",         date: "May 15, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned",
    // 30-participant training — session + venue + meals + mobilisation.
    activityContext: { mode: "staff", participants: 30 },
  },
  { id: "p-7", type: "Visit",               title: "Visit",             context: "Central Primary School", date: "May 14, 2025", weekLabel: "Week 3", filter: "in_school", status: "Verified" },
  { id: "p-8", type: "Visit",               title: "Visit",             context: "Rwenkoma Friends PS",    date: "May 15, 2025", weekLabel: "Week 3", filter: "in_school", status: "Planned" },
  // Week 4 — May 19-23: planned ahead, mostly not started.
  { id: "p-w4-1", type: "Visit",            title: "Visit",             context: "Living Word PS",         date: "May 19, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned" },
  { id: "p-w4-2", type: "Visit",            title: "Visit",             context: "Grace Community School", date: "May 20, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned",
    // Multi-school primary-district visit — 3 schools in one day.
    activityContext: { mode: "staff", districtType: "primary", schools: 3, days: 1 },
  },
  { id: "p-w4-3", type: "Cluster Training", title: "Cluster Training",  context: "Agago Hub Cluster",      date: "May 20, 2025", weekLabel: "Week 4", filter: "cluster",   status: "Planned" },
  { id: "p-w4-4", type: "Follow-Up Visit",  title: "Follow-Up Visit",   context: "Victory Academy",        date: "May 22, 2025", weekLabel: "Week 4", filter: "follow_up", status: "Planned" },
  { id: "p-w4-5", type: "Visit",            title: "Visit",             context: "Light of Hope School",   date: "May 23, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned" },
];

// ────────── CCEO plan — Core Schools field activities ──────────
//
// /my-plan is role-scoped: a Program Lead sees the team plan above, a
// CCEO sees their own Core Schools field plan below.

export type MonthSummary = typeof monthSummary;

export const cceoMonthSummary: MonthSummary = {
  weekStart: "May 12 – May 18",
  totals: [
    { key: "ssa_assessments", label: "SSA Assessments",    value: 9  },
    { key: "core_visits",     label: "Core School Visits", value: 12 },
    { key: "in_school",       label: "In-School Coaching", value: 6  },
    { key: "follow_ups",      label: "Follow-Up Visits",   value: 4  },
  ],
  monthFooters: [
    { key: "month_planned", label: "Planned Activities for Month", value: "24" },
    { key: "month_cost",    label: "Total Cost for Month",         value: "UGX 540K" },
  ],
  weekSummary: { plannedActivities: 14, totalCost: "UGX 150K" },
};

export const cceoPlanItems: PlanItem[] = [
  // Week 2 — May 5-9: completed core schools work.
  { id: "cp-w2-1", type: "Visit",           title: "SSA Assessment",     context: "Kabaale Primary School",        date: "May 5, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  { id: "cp-w2-2", type: "Visit",           title: "Core School Visit",  context: "Mawanga PS",                    date: "May 6, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  { id: "cp-w2-3", type: "Visit",           title: "In-School Coaching", context: "Greenfields Academy",           date: "May 7, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  { id: "cp-w2-4", type: "Follow-Up Visit", title: "Follow-Up Visit",    context: "St. Joseph PS",                 date: "May 8, 2025",  weekLabel: "Week 2", filter: "follow_up", status: "Verified" },
  { id: "cp-w2-5", type: "Visit",           title: "Core School Visit",  context: "Christ the King PS",            date: "May 9, 2025",  weekLabel: "Week 2", filter: "in_school", status: "Verified" },
  // Week 3 — May 12-15: current week.
  { id: "cp-1", type: "Visit",            title: "Core School Visit",  context: "St. Mary's Naguru",             date: "May 12, 2025", weekLabel: "Week 3", filter: "in_school", status: "In Progress"    },
  { id: "cp-2", type: "Visit",            title: "SSA Assessment",     context: "Bright Future Kamwokya",        date: "May 12, 2025", weekLabel: "Week 3", filter: "in_school", status: "Verified"       },
  { id: "cp-3", type: "Cluster Training", title: "Cluster Training",   context: "Christ-like Behavior — Naguru", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned"        },
  { id: "cp-4", type: "Visit",            title: "In-School Coaching", context: "Hilltop Bukoto",                date: "May 13, 2025", weekLabel: "Week 3", filter: "in_school", status: "Planned"        },
  { id: "cp-5", type: "Follow-Up Visit",  title: "Follow-Up Visit",    context: "Sunrise Kabalagala",            date: "May 14, 2025", weekLabel: "Week 3", filter: "follow_up", status: "Awaiting SF ID",
    proposedBy: "Esther Naluwu (CCEO)",
    reschedules: [
      { from: "May 8, 2025", to: "May 14, 2025", reason: "School closed / public holiday", movedBy: "Esther Naluwu (CCEO)", movedAt: "May 6, 2025 13:11" },
    ],
  },
  { id: "cp-6", type: "Visit",            title: "SSA Assessment",     context: "Excel Academy Ntinda",          date: "May 14, 2025", weekLabel: "Week 3", filter: "in_school", status: "Planned"        },
  { id: "cp-7", type: "Visit",            title: "Core School Visit",  context: "Royal Hill Bugolobi",           date: "May 15, 2025", weekLabel: "Week 3", filter: "in_school", status: "Planned"        },
  { id: "cp-8", type: "Cluster Meeting",  title: "Cluster Meeting",    context: "Ntinda Cluster",                date: "May 15, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned"        },
  // Week 4 — May 19-23: upcoming.
  { id: "cp-w4-1", type: "Visit",           title: "SSA Assessment",     context: "Pope Paul VI Memorial",          date: "May 19, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned" },
  { id: "cp-w4-2", type: "Visit",           title: "Core School Visit",  context: "Star of the Sea Academy",        date: "May 20, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned" },
  { id: "cp-w4-3", type: "Cluster Training", title: "Cluster Training", context: "Leadership Best Practice — Mukono", date: "May 21, 2025", weekLabel: "Week 4", filter: "cluster", status: "Planned" },
  { id: "cp-w4-4", type: "Visit",           title: "In-School Coaching", context: "Trinity Junior",                 date: "May 22, 2025", weekLabel: "Week 4", filter: "in_school", status: "Planned" },
];

// ────────── Office-role plans (Director / RVP / Finance / M&E / HR / Admin) ──────────
//
// Leadership and back-office roles plan review / approval / planning
// sessions rather than field visits; "Cluster Meeting" is the closest
// existing activity type. They share the generic monthSummary chrome.

const directorPlanItems: PlanItem[] = [
  { id: "dir-1", type: "Cluster Meeting", title: "Approve monthly plans — 4 teams",            context: "Director's Office", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster",   status: "In Progress" },
  { id: "dir-2", type: "Cluster Meeting", title: "Regional performance review — West",         context: "Virtual",           date: "May 15, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned" },
  { id: "dir-3", type: "Visit",           title: "Priority school inspection — St. Mary's PS", context: "North",             date: "May 17, 2025", weekLabel: "Week 3", filter: "in_school", status: "Planned" },
];

const rvpPlanItems: PlanItem[] = [
  { id: "rvp-1", type: "Cluster Meeting", title: "Country review — Uganda",           context: "Regional Office", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster", status: "In Progress" },
  { id: "rvp-2", type: "Cluster Meeting", title: "Annual operating cycle gateway",     context: "Region-wide",     date: "May 14, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
  { id: "rvp-3", type: "Cluster Meeting", title: "Quarterly target sync — Directors",  context: "Virtual",         date: "May 16, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
];

const accountantPlanItems: PlanItem[] = [
  { id: "acc-1", type: "Cluster Meeting", title: "Weekly disbursement batch — Week 3", context: "Finance Office", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster", status: "Verified" },
  { id: "acc-2", type: "Cluster Meeting", title: "Review fund requests — 6 teams",     context: "Finance Office", date: "May 14, 2025", weekLabel: "Week 3", filter: "cluster", status: "In Progress" },
  { id: "acc-3", type: "Cluster Meeting", title: "Expense reconciliation cycle",       context: "Finance Office", date: "May 16, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
];

const impactPlanItems: PlanItem[] = [
  { id: "ia-1", type: "Visit",           title: "Verification visit — Northstar PS", context: "North",      date: "May 13, 2025", weekLabel: "Week 3", filter: "in_school", status: "In Progress" },
  { id: "ia-2", type: "Cluster Meeting", title: "Quality check batch review",        context: "M&E Office", date: "May 14, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Planned" },
  { id: "ia-3", type: "Cluster Meeting", title: "Partner performance review",        context: "Virtual",    date: "May 16, 2025", weekLabel: "Week 3", filter: "cluster",   status: "Awaiting SF ID" },
];

const hrPlanItems: PlanItem[] = [
  { id: "hr-1", type: "Cluster Meeting", title: "Performance review — North leads", context: "HR Office", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster", status: "In Progress" },
  { id: "hr-2", type: "Cluster Meeting", title: "Staff support case review",        context: "HR Office", date: "May 15, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
  { id: "hr-3", type: "Cluster Meeting", title: "Quarterly performance kickoff",    context: "All teams", date: "May 16, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
];

const adminPlanItems: PlanItem[] = [
  { id: "adm-1", type: "Cluster Meeting", title: "User access review",        context: "Admin Console", date: "May 13, 2025", weekLabel: "Week 3", filter: "cluster", status: "In Progress" },
  { id: "adm-2", type: "Cluster Meeting", title: "Audit log review — Week 19", context: "Admin Console", date: "May 14, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
  { id: "adm-3", type: "Cluster Meeting", title: "Quarterly config review",    context: "Platform",      date: "May 16, 2025", weekLabel: "Week 3", filter: "cluster", status: "Planned" },
];

const PLAN_ITEMS_BY_ROLE: Partial<Record<EdifyRole, PlanItem[]>> = {
  CountryDirector:   directorPlanItems,
  RVP:               rvpPlanItems,
  ProgramAccountant: accountantPlanItems,
  ImpactAssessment:  impactPlanItems,
  HumanResource:     hrPlanItems,
  Admin:             adminPlanItems,
};

// Every role gets a purpose-built plan: CCEO has its own month summary;
// other roles get role-specific items with the generic monthSummary.
// Program Lead (and any unknown role) keeps the rich shared plan.
export function planDataForRole(role: EdifyRole): { items: PlanItem[]; summary: MonthSummary } {
  if (role === "CCEO") return { items: cceoPlanItems, summary: cceoMonthSummary };
  return { items: PLAN_ITEMS_BY_ROLE[role] ?? planItems, summary: monthSummary };
}

// ────────── Screen 3 · Smart Route Planner ──────────
//
// Desktop counterpart: /dashboards/cpl#smart-route. Same RouteCceo rows
// regrouped by stop sequence for the mobile route runner.

export type RouteQualityLabel = "Excellent" | "Good" | "Average" | "Poor";

export const routeWeek = { label: "Week 3", range: "May 12 – May 18, 2025" };

export const routeInsight = {
  schools: 8,
  routes: 2,
  rating: "Excellent" as RouteQualityLabel,
  distanceKm: 56,
  travelTime: "2h 45m",
  routeQuality: "High",
};

export type RouteStop = {
  seq: number;
  schoolName: string;
  cluster: string;
  type: "Cluster Training" | "School Visit" | "Partner Follow-Up" | "Cluster Meeting";
  isStart?: boolean;
};

export type RouteGroup = {
  id: string;
  name: string;
  schoolsCount: number;
  distanceKm: number;
  travelTime: string;
  rating: RouteQualityLabel;
  stops: RouteStop[];
};

export const routeGroups: RouteGroup[] = [
  {
    id: "r-1",
    name: "Kitgum Town Route",
    schoolsCount: 4,
    distanceKm: 24,
    travelTime: "1h 20m",
    rating: "Excellent",
    stops: [
      { seq: 1, schoolName: "Kitgum Central Cluster", cluster: "Cluster Training", type: "Cluster Training", isStart: true },
      { seq: 2, schoolName: "Pope John Primary School", cluster: "School Visit",    type: "School Visit"  },
      { seq: 3, schoolName: "St. Peter Primary School", cluster: "School Visit",    type: "School Visit"  },
      { seq: 4, schoolName: "Kal Primary School",       cluster: "School Visit",    type: "School Visit"  },
    ],
  },
  {
    id: "r-2",
    name: "Orom Route",
    schoolsCount: 4,
    distanceKm: 32,
    travelTime: "1h 25m",
    rating: "Good",
    stops: [
      { seq: 1, schoolName: "Orom Cluster",           cluster: "Cluster Meeting",   type: "Cluster Meeting", isStart: true },
      { seq: 2, schoolName: "Nigina UMEA",            cluster: "Partner Follow-Up", type: "Partner Follow-Up" },
      { seq: 3, schoolName: "Rwenkoma Friends PS",    cluster: "School Visit",      type: "School Visit"  },
      { seq: 4, schoolName: "Matidi Primary School",  cluster: "School Visit",      type: "School Visit"  },
    ],
  },
];

// ────────── Screen 4 · Priority Schools + School Brief ──────────
//
// Desktop counterpart: /schools (Schools Directory) → priority panel.
// School-Brief detail card mirrors the School 360 panel shown there.

export type PrioritySort = "priority" | "ssa" | "latest_visit";

export type PriorityIssue =
  | "Low SSA Performance"
  | "No Visit"
  | "No Training"
  | "Neither Training nor Visit"
  | "Inactive";

export type PrioritySchoolItem = {
  id: string;
  rank: number;
  schoolName: string;
  cluster: string;
  issue: PriorityIssue;
  ssaPercent: number;
  highlighted?: boolean;
};

export const prioritySchools: PrioritySchoolItem[] = [
  { id: "ps-1", rank: 1, schoolName: "St. Agnes Primary School",  cluster: "Kitgum Central Cluster", issue: "Low SSA Performance",        ssaPercent: 38, highlighted: true },
  { id: "ps-2", rank: 2, schoolName: "St. Peter Primary School",  cluster: "Pakele Cluster",         issue: "No Visit",                   ssaPercent: 36 },
  { id: "ps-3", rank: 3, schoolName: "Gwang Primary School",      cluster: "Orom Cluster",           issue: "No Training",                ssaPercent: 36 },
  { id: "ps-4", rank: 4, schoolName: "Orom UMEA School",          cluster: "Orom Cluster",           issue: "Neither Training nor Visit", ssaPercent: 35 },
  { id: "ps-5", rank: 5, schoolName: "Matidi Primary School",     cluster: "Matidi Cluster",         issue: "Inactive",                   ssaPercent: 25 },
];

export type PendingTaskCadence = "This Week" | "This Month" | "Next Month";

export type PrioritySchoolBrief = {
  schoolId: string;
  schoolName: string;
  performance: PriorityIssue;
  contactName: string;
  contactRole: string;
  contactPhone: string;
  district: string;
  ssaWeakestIntervention: string;
  recommendedTraining: string;
  latestVisit: { date: string; ago: string };
  lastTraining: { date: string; ago: string };
  pendingTasks: { id: string; label: string; cadence: PendingTaskCadence }[];
};

export const stAgnesBrief: PrioritySchoolBrief = {
  schoolId: "ps-1",
  schoolName: "St. Agnes Primary School",
  performance: "Low SSA Performance",
  contactName: "Jane Adwong",
  contactRole: "(HT)",
  contactPhone: "+256 772 345 678",
  district: "Kitgum",
  ssaWeakestIntervention: "SSA Follow-Up",
  recommendedTraining: "SSA Follow-Up",
  latestVisit: { date: "Apr 22, 2025", ago: "3w ago" },
  lastTraining: { date: "Mar 12, 2025", ago: "9w ago" },
  pendingTasks: [
    { id: "pt-1", label: "Plan and conduct school visit",  cadence: "This Week" },
    { id: "pt-2", label: "Conduct SSA follow-up training", cadence: "This Month" },
    { id: "pt-3", label: "Verify improvement plan",        cadence: "Next Month" },
  ],
};

// ────────── Screen 5 · Salesforce Completion Queue ──────────
//
// Desktop counterpart: /dashboards/impact (Impact Assessment / M&E console).
// Same verification workflow — queue items move through the same status
// machine: Awaiting SF ID → Submitted → Verified (or Returned).

export type SfStatus = "Awaiting SF ID" | "Submitted" | "Returned" | "Verified";
export type SfFilter = "all" | "cluster" | "in_school" | "follow_up";

export const sfQueueCounts = {
  awaiting:  11,
  submitted: 5,
  returned:  2,
  verified:  42,
};

export type SfQueueItem = {
  id: string;
  schoolName: string;
  contextLabel: string; // "School Visit", "Cluster Meeting", "Partner Follow-Up Visit"
  weekLabel: string;
  dateRange: string;
  status: SfStatus;
  filter: SfFilter;
  recordId?: string;
};

// ────────── Screen 6 · Today's Tasks ──────────
//
// Planned activities for the current field day, grouped by part of day.
// Anchored to "May 12, 2025" — the same anchor the rest of the mocks use,
// so totals stay consistent with `planItems` and the verified leaderboard.

export type TodaysTaskKind =
  | "Cluster Training"
  | "Cluster Meeting"
  | "School Visit"
  | "Follow-Up Visit"
  | "Partner Meeting"
  | "SSA Verification";

export type TodaysTaskStatus =
  | "Planned"
  | "In Progress"
  | "Completed"
  | "Overdue";

export type TodaysTaskBlock = "Morning" | "Afternoon" | "Evening";

export type TodaysTask = {
  id: string;
  block: TodaysTaskBlock;
  startTime: string;     // "08:30"
  endTime: string;       // "10:00"
  kind: TodaysTaskKind;
  title: string;
  location: string;
  cluster: string;
  status: TodaysTaskStatus;
  priority: "High" | "Medium" | "Low";
  hasSalesforceId?: boolean;
};

export const todayHeader = {
  dateLabel: "Mon, May 12, 2025",
  shortDate: "May 12",
  weekLabel: "Week 3",
};

export const todaysTasks: TodaysTask[] = [
  { id: "td-1", block: "Morning",   startTime: "08:00", endTime: "09:00", kind: "Cluster Training", title: "Cluster Training — Leadership Best Practice", location: "Kitgum Central Cluster Hub",  cluster: "Kitgum Central",  status: "Completed",   priority: "High",   hasSalesforceId: true },
  { id: "td-2", block: "Morning",   startTime: "09:30", endTime: "10:30", kind: "School Visit",     title: "School Visit — Pope John PS",                  location: "Pope John Primary School",    cluster: "Kitgum Central",  status: "In Progress", priority: "High" },
  { id: "td-3", block: "Morning",   startTime: "11:00", endTime: "12:00", kind: "School Visit",     title: "School Visit — St. Peter PS",                  location: "St. Peter Primary School",    cluster: "Pakele",          status: "Planned",     priority: "High" },
  { id: "td-4", block: "Afternoon", startTime: "13:30", endTime: "14:30", kind: "Follow-Up Visit",  title: "Follow-Up Visit — Nigina UMEA",                location: "Nigina UMEA",                 cluster: "Orom",            status: "Planned",     priority: "Medium" },
  { id: "td-5", block: "Afternoon", startTime: "15:00", endTime: "16:00", kind: "SSA Verification", title: "SSA Verification — Kal PS",                    location: "Kal Primary School",          cluster: "Kitgum Central",  status: "Planned",     priority: "Medium" },
  { id: "td-6", block: "Afternoon", startTime: "16:30", endTime: "17:30", kind: "Partner Meeting",  title: "Partner Meeting — Compassion Intl.",           location: "Compassion Field Office",     cluster: "Kitgum Town",     status: "Overdue",     priority: "High" },
  { id: "td-7", block: "Evening",   startTime: "18:00", endTime: "18:30", kind: "Cluster Meeting",  title: "Cluster Meeting Debrief",                      location: "Virtual (WhatsApp)",          cluster: "Orom",            status: "Planned",     priority: "Low" },
];

export const todaysTaskCounts = {
  total:       todaysTasks.length,
  completed:   todaysTasks.filter((t) => t.status === "Completed").length,
  inProgress:  todaysTasks.filter((t) => t.status === "In Progress").length,
  planned:     todaysTasks.filter((t) => t.status === "Planned").length,
  overdue:     todaysTasks.filter((t) => t.status === "Overdue").length,
};

// ────────── Screen 7 · Create / Edit Plan (FAB destination) ──────────
//
// The central + button on the mobile bottom nav launches the plan builder.
// It opens to a list of *High Priority Schools* — schools the planner
// engine has flagged based on SSA + visit/training history. The CCEO picks
// schools to add to their plan, then commits the selection on Continue.

export type PlanActivityType =
  | "School Visit"
  | "Training"
  | "SSA Follow-Up"
  | "Cluster Meeting";

export type PriorityPlanCandidate = {
  id: string;
  rank: number;
  schoolName: string;
  cluster: string;
  district: string;
  issue: PriorityIssue;
  ssaPercent: number;
  recommended: PlanActivityType;
  // why the planner suggested it (one short line)
  reason: string;
  // proposed week to slot the activity into
  suggestedWeek: string; // "Week 3 · May 12 – 18"
  distanceKm: number;
};

export const priorityPlanCandidates: PriorityPlanCandidate[] = [
  { id: "pc-1", rank: 1, schoolName: "St. Agnes Primary School",  cluster: "Kitgum Central Cluster", district: "Kitgum",  issue: "Low SSA Performance",        ssaPercent: 38, recommended: "SSA Follow-Up", reason: "SSA 38% · No visit in 3 weeks",      suggestedWeek: "Week 3 · May 12 – 18",  distanceKm: 6  },
  { id: "pc-2", rank: 2, schoolName: "St. Peter Primary School",  cluster: "Pakele Cluster",         district: "Adjumani", issue: "No Visit",                  ssaPercent: 36, recommended: "School Visit",  reason: "No visit logged this term",          suggestedWeek: "Week 3 · May 12 – 18",  distanceKm: 18 },
  { id: "pc-3", rank: 3, schoolName: "Gwang Primary School",      cluster: "Orom Cluster",           district: "Kitgum",   issue: "No Training",               ssaPercent: 36, recommended: "Training",      reason: "No training this term · SSA dropping", suggestedWeek: "Week 4 · May 19 – 25",  distanceKm: 22 },
  { id: "pc-4", rank: 4, schoolName: "Orom UMEA School",          cluster: "Orom Cluster",           district: "Kitgum",   issue: "Neither Training nor Visit",ssaPercent: 35, recommended: "School Visit",  reason: "No visit, no training this term",    suggestedWeek: "Week 3 · May 12 – 18",  distanceKm: 24 },
  { id: "pc-5", rank: 5, schoolName: "Matidi Primary School",     cluster: "Matidi Cluster",         district: "Kitgum",   issue: "Inactive",                  ssaPercent: 25, recommended: "School Visit",  reason: "Becoming inactive · last visit 8 wks", suggestedWeek: "Week 4 · May 19 – 25",  distanceKm: 28 },
  { id: "pc-6", rank: 6, schoolName: "Kal Primary School",        cluster: "Kitgum Central Cluster", district: "Kitgum",   issue: "Low SSA Performance",        ssaPercent: 41, recommended: "SSA Follow-Up", reason: "SSA 41% · improvement plan due",     suggestedWeek: "Week 4 · May 19 – 25",  distanceKm: 8  },
  { id: "pc-7", rank: 7, schoolName: "Pope John Primary School",  cluster: "Kitgum Central Cluster", district: "Kitgum",   issue: "No Training",               ssaPercent: 47, recommended: "Training",      reason: "Trainings overdue · cluster cohort", suggestedWeek: "Week 5 · May 26 – Jun 1", distanceKm: 5  },
  { id: "pc-8", rank: 8, schoolName: "Rwenkoma Friends PS",       cluster: "Orom Cluster",           district: "Kitgum",   issue: "No Visit",                  ssaPercent: 49, recommended: "School Visit",  reason: "No visit logged · cluster sweep",    suggestedWeek: "Week 5 · May 26 – Jun 1", distanceKm: 26 },
];

export const planBuilderHeader = {
  title: "Create / Edit Plan",
  subtitle: "Pick high-priority schools and slot them into your plan.",
  monthLabel: "May 2025",
  totalCandidates: priorityPlanCandidates.length,
};

export const todayQuickActions = [
  { key: "log_visit",   label: "Log Visit",        icon: "logVisit" as const, href: "/queue" },
  { key: "smart_route", label: "Smart Route",      icon: "route"    as const, href: "/route" },
];

export const sfQueueItems: SfQueueItem[] = [
  { id: "sf-1", schoolName: "Pope John Primary School",  contextLabel: "School Visit",          weekLabel: "Week 3", dateRange: "May 12 – 18", status: "Awaiting SF ID", filter: "in_school" },
  { id: "sf-2", schoolName: "St. Peter Primary School",  contextLabel: "School Visit",          weekLabel: "Week 3", dateRange: "May 12 – 18", status: "Awaiting SF ID", filter: "in_school" },
  { id: "sf-3", schoolName: "Orom Cluster",              contextLabel: "Cluster Meeting",       weekLabel: "Week 3", dateRange: "May 12 – 18", status: "Awaiting SF ID", filter: "cluster"   },
  { id: "sf-4", schoolName: "Nigina UMEA",               contextLabel: "Partner Follow-Up Visit", weekLabel: "May 14, 2025", dateRange: "", status: "Submitted",       filter: "follow_up", recordId: "5003J00001Abc09" },
];
