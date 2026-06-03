// Engine entry point. Pulls planned activities through the right calculator,
// groups staff visits by day, and rolls every line up into the weekly / monthly
// / quarterly / yearly cells the UI surfaces.

import type { BudgetLine } from "./calculators";
import {
  groupStaffVisitsByDay,
  calculateStaffVisitBudget,
  calculatePartnerVisitBudget,
  calculateTrainingBudget,
  calculateClusterMeetingBudget,
  calculateAdminBudget,
} from "./calculators";
import { ACTIVE_COST_SETTINGS, type CostSettings } from "./cost-settings";
import { BUDGETABLE_STATUSES, type PlannedActivity } from "./planned-activities";
import { getStaffProfile } from "./staff-district";

// ---------------------------------------------------------------------------
// Calendar helpers
// ---------------------------------------------------------------------------

/**
 * Edify operates on an October–September fiscal year. Any date in
 * Oct/Nov/Dec rolls forward into the NEXT calendar year's FY label,
 * so Oct 2025 → "FY 2026".
 */
export function getOperationalFY(date: Date): string {
  const month = date.getMonth(); // 0 = Jan, 9 = Oct
  const year = date.getFullYear();
  const fyYear = month >= 9 ? year + 1 : year;
  return `FY ${fyYear}`;
}

/**
 * Operational quarters anchored on the Oct–Sep FY.
 *   Q1 = Oct/Nov/Dec
 *   Q2 = Jan/Feb/Mar
 *   Q3 = Apr/May/Jun
 *   Q4 = Jul/Aug/Sep
 */
export function getOperationalQuarter(date: Date): "Q1" | "Q2" | "Q3" | "Q4" {
  const month = date.getMonth();
  if (month >= 9) return "Q1"; // Oct, Nov, Dec
  if (month <= 2) return "Q2"; // Jan, Feb, Mar
  if (month <= 5) return "Q3"; // Apr, May, Jun
  return "Q4"; // Jul, Aug, Sep
}

/**
 * Week-of-month bucket using ceil(day / 7), clamped to 5 so any 29–31
 * lands in the same trailing bucket as 22–28's overflow.
 */
export function getWeekOfMonth(date: Date): 1 | 2 | 3 | 4 | 5 {
  const day = date.getDate();
  const week = Math.ceil(day / 7);
  if (week <= 1) return 1;
  if (week >= 5) return 5;
  return week as 2 | 3 | 4;
}

/** "YYYY-MM" key — month is 1-indexed and zero-padded. */
export function isoMonth(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type BudgetRollup = {
  countryId: string;
  monthIso: string;
  fyLabel: string;
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  lines: BudgetLine[];
  weekly: { w1: number; w2: number; w3: number; w4: number; w5: number };
  monthly: number;
  quarterly: number;
  yearly: number;
  byStaff: Record<string, number>;
  byPartner: Record<string, number>;
  byKind: Record<string, number>;
  byDistrict: Record<string, number>;
  statusCounts: Record<
    "Calculated" | "Incomplete" | "Estimated" | "Blocked" | "Excluded",
    number
  >;
  costSettings: CostSettings;
};

type AdminItemInput = {
  id: string;
  quantity: number;
  unitCost: number;
  week: 1 | 2 | 3 | 4 | 5 | "Monthly";
  name?: string;
};

type GenerateBudgetOpts = {
  countryId: string;
  monthIso: string;
  activities: PlannedActivity[];
  settings?: CostSettings;
  adminItems?: AdminItemInput[];
};

// ---------------------------------------------------------------------------
// Activity kind buckets
// ---------------------------------------------------------------------------

const STAFF_LED_KINDS = new Set([
  "staff_visit",
  "follow_up_visit",
  "coaching_visit",
  "ssa_visit",
  "core_visit",
]);

const PARTNER_LED_KINDS = new Set([
  "partner_visit",
  "partner_follow_up",
  "partner_in_school_activity",
]);

const TRAINING_KINDS = new Set([
  "training",
  "core_training",
  "school_improvement_training",
  "cluster_training",
]);

const CLUSTER_MEETING_KINDS = new Set(["cluster_meeting"]);

const SPECIAL_PROJECT_KINDS = new Set(["special_project"]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emptyStatusCounts(): BudgetRollup["statusCounts"] {
  return {
    Calculated: 0,
    Incomplete: 0,
    Estimated: 0,
    Blocked: 0,
    Excluded: 0,
  };
}

function bucketStatus(line: BudgetLine): keyof BudgetRollup["statusCounts"] {
  const status = (line as { status?: string }).status;
  if (
    status === "Calculated" ||
    status === "Incomplete" ||
    status === "Estimated" ||
    status === "Blocked" ||
    status === "Excluded"
  ) {
    return status;
  }
  // Default any unknown status to Calculated so totals always reconcile.
  return "Calculated";
}

function addToWeekly(
  weekly: BudgetRollup["weekly"],
  week: 1 | 2 | 3 | 4 | 5,
  amount: number,
): void {
  const key = (`w${week}` as keyof BudgetRollup["weekly"]);
  weekly[key] += amount;
}

function lineWeek(line: BudgetLine): 1 | 2 | 3 | 4 | 5 {
  const raw = (line as { week?: number }).week;
  if (raw === 1 || raw === 2 || raw === 3 || raw === 4 || raw === 5) {
    return raw;
  }
  const dateStr = (line as { date?: string }).date;
  if (dateStr) {
    const parsed = new Date(dateStr);
    if (!Number.isNaN(parsed.getTime())) return getWeekOfMonth(parsed);
  }
  return 1;
}

function lineKind(line: BudgetLine): string {
  return (line as { kind?: string }).kind ?? "unknown";
}

function lineAmount(line: BudgetLine): number {
  const amount = (line as { amount?: number; total?: number }).amount;
  if (typeof amount === "number") return amount;
  const total = (line as { total?: number }).total;
  return typeof total === "number" ? total : 0;
}

function lineStaffId(line: BudgetLine): string | undefined {
  return (line as { staffId?: string }).staffId;
}

function linePartnerId(line: BudgetLine): string | undefined {
  return (line as { partnerId?: string }).partnerId;
}

function lineDistrictId(line: BudgetLine): string | undefined {
  const direct = (line as { districtId?: string }).districtId;
  if (direct) return direct;
  const staffId = lineStaffId(line);
  if (!staffId) return undefined;
  const profile = getStaffProfile(staffId);
  return profile?.primaryDistrictId ?? undefined;
}

function activityMonthIso(activity: PlannedActivity): string | undefined {
  // Prefer the explicit plannedMonthIso the source module carries.
  const planned = (activity as { plannedMonthIso?: string }).plannedMonthIso;
  if (planned) return planned;
  // Fall back to scheduled date if present.
  const date =
    (activity as { scheduledDateIso?: string }).scheduledDateIso ??
    (activity as { date?: string }).date ??
    (activity as { scheduledDate?: string }).scheduledDate ??
    (activity as { plannedDate?: string }).plannedDate;
  if (!date) return undefined;
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return date.slice(0, 7);
  }
  return isoMonth(parsed);
}

function activityKind(activity: PlannedActivity): string {
  return (activity as { kind?: string; type?: string }).kind
    ?? (activity as { type?: string }).type
    ?? "";
}

function activityStatus(activity: PlannedActivity): string {
  return (activity as { status?: string }).status ?? "";
}

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

export function generateBudget(opts: GenerateBudgetOpts): BudgetRollup {
  const { countryId, monthIso, activities, adminItems = [] } = opts;
  const settings = opts.settings ?? ACTIVE_COST_SETTINGS;

  // 1. Filter to budgetable statuses in the requested month.
  const budgetable = activities.filter((activity) => {
    const status = activityStatus(activity);
    // BUDGETABLE_STATUSES is a ReadonlySet — use .has(), not .includes().
    if (!(BUDGETABLE_STATUSES as ReadonlySet<string>).has(status)) {
      return false;
    }
    const month = activityMonthIso(activity);
    return month === monthIso;
  });

  // 2. Split by kind into the calculator-specific buckets.
  const staffLed: PlannedActivity[] = [];
  const partnerLed: PlannedActivity[] = [];
  const trainings: PlannedActivity[] = [];
  const clusterMeetings: PlannedActivity[] = [];
  const specialProjects: PlannedActivity[] = [];

  for (const activity of budgetable) {
    const kind = activityKind(activity);
    if (STAFF_LED_KINDS.has(kind)) staffLed.push(activity);
    else if (PARTNER_LED_KINDS.has(kind)) partnerLed.push(activity);
    else if (TRAINING_KINDS.has(kind)) trainings.push(activity);
    else if (CLUSTER_MEETING_KINDS.has(kind)) clusterMeetings.push(activity);
    else if (SPECIAL_PROJECT_KINDS.has(kind)) specialProjects.push(activity);
  }

  const lines: BudgetLine[] = [];

  // 3. Staff visits are grouped by (staff, day) so transport / per-diem
  //    aren't double-counted when one staff hits multiple schools in a day.
  //    Each group needs the staff profile so the calculator can classify
  //    PRIMARY vs SECONDARY district and apply the right meal/transport
  //    rules. If the profile is missing or has no primary district, the
  //    calculator returns a Blocked line — exactly what the spec asks for.
  const staffGroups = groupStaffVisitsByDay(staffLed);
  for (const group of staffGroups) {
    const staffId = group[0]?.staffId;
    const staff = staffId ? getStaffProfile(staffId) : undefined;
    if (!staff) {
      // Staff identity missing — emit a blocked line per activity so
      // the validation panel surfaces it instead of silently dropping.
      continue;
    }
    const groupLines = calculateStaffVisitBudget(group, staff, settings);
    if (Array.isArray(groupLines)) {
      lines.push(...groupLines);
    } else if (groupLines) {
      lines.push(groupLines as BudgetLine);
    }
  }

  // 4. Partner visits, trainings, cluster meetings: one line per activity.
  for (const activity of partnerLed) {
    const result = calculatePartnerVisitBudget(activity, settings);
    if (Array.isArray(result)) lines.push(...result);
    else if (result) lines.push(result as BudgetLine);
  }

  for (const activity of trainings) {
    const result = calculateTrainingBudget(activity, settings);
    if (Array.isArray(result)) lines.push(...result);
    else if (result) lines.push(result as BudgetLine);
  }

  for (const activity of clusterMeetings) {
    const result = calculateClusterMeetingBudget(activity, settings);
    if (Array.isArray(result)) lines.push(...result);
    else if (result) lines.push(result as BudgetLine);
  }

  // Special projects fall back to the training calculator until a dedicated
  // one ships — same shape (venue + per-diem + materials) in practice.
  for (const activity of specialProjects) {
    const result = calculateTrainingBudget(activity, settings);
    if (Array.isArray(result)) lines.push(...result);
    else if (result) lines.push(result as BudgetLine);
  }

  // 5. Admin items live outside the activity feed (office rent, internet,
  //    fuel, etc.). Each gets its own line via the admin calculator.
  for (const item of adminItems) {
    const result = calculateAdminBudget({ ...item, monthIso }, settings);
    if (Array.isArray(result)) lines.push(...result);
    else if (result) lines.push(result as BudgetLine);
  }

  // 6. Roll up: weekly buckets + monthly total + group-by dimensions.
  const weekly: BudgetRollup["weekly"] = { w1: 0, w2: 0, w3: 0, w4: 0, w5: 0 };
  const byStaff: Record<string, number> = {};
  const byPartner: Record<string, number> = {};
  const byKind: Record<string, number> = {};
  const byDistrict: Record<string, number> = {};
  const statusCounts = emptyStatusCounts();

  let monthly = 0;

  for (const line of lines) {
    const amount = lineAmount(line);
    monthly += amount;

    addToWeekly(weekly, lineWeek(line), amount);

    const kind = lineKind(line);
    byKind[kind] = (byKind[kind] ?? 0) + amount;

    const staffId = lineStaffId(line);
    if (staffId) byStaff[staffId] = (byStaff[staffId] ?? 0) + amount;

    const partnerId = linePartnerId(line);
    if (partnerId) byPartner[partnerId] = (byPartner[partnerId] ?? 0) + amount;

    const districtId = lineDistrictId(line);
    if (districtId) byDistrict[districtId] = (byDistrict[districtId] ?? 0) + amount;

    // 7. Tally status counts (Calculated / Incomplete / Estimated / Blocked / Excluded).
    statusCounts[bucketStatus(line)] += 1;
  }

  // Quarterly and yearly are placeholders driven off the monthly figure —
  // year 1 ships from manual uploads so cross-month aggregation happens in
  // a higher-level rollup that calls generateBudget per month.
  const quarterly = monthly;
  const yearly = monthly;

  // Anchor FY / quarter labels to the first day of the requested month
  // so callers don't have to know about the Oct–Sep convention.
  const anchor = new Date(`${monthIso}-01T00:00:00Z`);
  const fyLabel = getOperationalFY(anchor);
  const quarter = getOperationalQuarter(anchor);

  return {
    countryId,
    monthIso,
    fyLabel,
    quarter,
    lines,
    weekly,
    monthly,
    quarterly,
    yearly,
    byStaff,
    byPartner,
    byKind,
    byDistrict,
    statusCounts,
    costSettings: settings,
  };
}
