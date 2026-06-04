// Monthly Fund Request — mock generator.
//
// Stands in for the real backend that will produce a MonthlyFundRequest
// by aggregating approved monthly-plan activities + applying the
// active CD cost settings. The shape MUST mirror what the real query
// will return so the UI stops at the type boundary, not at the
// fixture.
//
// Phase 3: This module is now a thin adapter on top of the deterministic
// budget engine in `./budget/*`. It pulls planned activities, runs the
// engine, then maps the resulting BudgetRollup onto the legacy
// MonthlyFundRequest shape the UI already consumes. The hand-rolled
// per-staff seeds were removed — every number on screen now comes from
// the engine.
//
// `generateMonthlyFundRequest()` is the entry point used by the page.
// It returns a fully populated MFR with lines, sources, and admin
// items already attached, so the page can render purely from the
// returned object without further DB calls.

import {
  ACTIVE_COST_SETTINGS as ENGINE_COST_SETTINGS,
  type CostSettings,
} from "./budget/cost-settings";
import {
  calculateAdminBudget,
  type BudgetLine,
} from "./budget/calculators";
import {
  getPlannedActivities,
  type PlannedActivity,
} from "./budget/planned-activities";
import { generateBudget, type BudgetRollup } from "./budget/rollup";
import { getStaffProfile } from "./budget/staff-district";
import type {
  AdminBudgetCategory,
  CategoryCell,
  MfrActivityCategory,
  MfrAdminItem,
  MfrApprovalEvent,
  MfrCostSettingsSnapshot,
  MfrLine,
  MfrSourceRecord,
  MfrValidationIssue,
  MonthlyFundRequest,
  WeekBuckets,
} from "./monthly-fund-request-types";

// ────────── Seeded admin items ───────────────────────────────────────
//
// CD-curated administration line items. Fed to the engine's
// calculateAdminBudget via generateBudget(adminItems), then echoed out
// to the UI as MfrAdminItem rows.

export type SeedAdminItem = {
  id: string;
  category: AdminBudgetCategory;
  name: string;
  quantity: number;
  unitCost: number;
  week: 1 | 2 | 3 | 4 | 5 | "Monthly";
  justification?: string;
};

export const SEEDED_ADMIN_ITEMS: SeedAdminItem[] = [
  { id: "adm-1", category: "Rent",                    name: "Country office rent",                          quantity: 1,  unitCost: 2_500_000, week: "Monthly", justification: "Monthly office lease" },
  { id: "adm-2", category: "Internet",                name: "Office fibre + 4G backup",                     quantity: 1,  unitCost: 850_000,   week: "Monthly", justification: "Always-on connectivity for analytics + reporting" },
  { id: "adm-3", category: "Airtime",                 name: "Staff airtime allocation",                     quantity: 18, unitCost: 60_000,    week: "Monthly", justification: "Field communication for 18 active staff" },
  { id: "adm-4", category: "OfficeSupplies",          name: "Office supplies refill",                       quantity: 1,  unitCost: 420_000,   week: 2,         justification: "Quarterly supplies refill window" },
  { id: "adm-5", category: "Printing",                name: "Training materials print run",                 quantity: 1,  unitCost: 1_650_000, week: 3,         justification: "ToT printed materials for April sessions" },
  { id: "adm-6", category: "BankCharges",             name: "Monthly bank charges",                         quantity: 1,  unitCost: 220_000,   week: "Monthly", justification: "Standard country banking fees" },
  { id: "adm-7", category: "AdministrationTransport", name: "Admin transport — week 2 country visit",       quantity: 1,  unitCost: 480_000,   week: 2,         justification: "CD field assurance visit" },
];

// ────────── Admin-item overlay (CD-editable, persisted) ──────────────
//
// SEEDED_ADMIN_ITEMS is the immutable baseline. The CD's add/edit/remove
// operations mutate this globalThis-backed overlay (seeded from the
// baseline on first read), and the request engine reads `effectiveAdminItems()`
// so changes flow into the budget rollup + grand total. Shaped like a future
// Prisma `MfrAdminItem` table; the swap replaces the array ops with Prisma.

const ADMIN_OVERLAY_KEY = "__edify_mfr_admin_items__";
type GlobalWithAdminOverlay = typeof globalThis & { [ADMIN_OVERLAY_KEY]?: SeedAdminItem[] };

function adminOverlay(): SeedAdminItem[] {
  const g = globalThis as GlobalWithAdminOverlay;
  if (!g[ADMIN_OVERLAY_KEY]) g[ADMIN_OVERLAY_KEY] = SEEDED_ADMIN_ITEMS.map((x) => ({ ...x }));
  return g[ADMIN_OVERLAY_KEY]!;
}

export function effectiveAdminItems(): SeedAdminItem[] {
  return adminOverlay();
}

export function addAdminItemRecord(input: Omit<SeedAdminItem, "id">): SeedAdminItem {
  const rec: SeedAdminItem = { ...input, id: `adm-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}` };
  adminOverlay().push(rec);
  return rec;
}

export function updateAdminItemRecord(id: string, patch: Partial<Omit<SeedAdminItem, "id">>): SeedAdminItem | undefined {
  const a = adminOverlay();
  const i = a.findIndex((x) => x.id === id);
  if (i === -1) return undefined;
  a[i] = { ...a[i], ...patch };
  return a[i];
}

export function removeAdminItemRecord(id: string): boolean {
  const a = adminOverlay();
  const i = a.findIndex((x) => x.id === id);
  if (i === -1) return false;
  a.splice(i, 1);
  return true;
}

export function __resetAdminItemOverlay() {
  const g = globalThis as GlobalWithAdminOverlay;
  g[ADMIN_OVERLAY_KEY] = undefined;
}

// ────────── Cost-settings snapshot shim ──────────────────────────────
//
// The legacy MfrCostSettingsSnapshot has more fields than the new
// CostSettings carries. We populate what we can from the engine and
// zero out the rest — the UI tolerates zero cells.

function toLegacyCostSnapshot(settings: CostSettings): MfrCostSettingsSnapshot {
  return {
    versionId:     settings.versionId,
    fyLabel:       settings.fyLabel,
    capturedAtIso: settings.capturedAtIso,

    staffVisitCostPerVisit:   0,
    partnerVisitLumpSum:      settings.partnerVisitLumpSum,
    partnerVisitCostPerVisit: settings.partnerVisitLumpSum,
    ssaCostPerActivity:       0,

    primaryDistrictTransportPerSchool:   settings.staffPrimaryTransportPerSchool,
    secondaryDistrictTransportPerSchool: settings.staffSecondaryTransportPerSchool,

    clusterTrainingPerSchool:           0,
    clusterTrainingSessionFee:          settings.trainingSessionFee,
    groupTrainingPerSchool:             0,
    inSchoolTrainingPerSchool:          0,
    trainingVenueFee:                   settings.trainingVenueFee,
    trainingMobilisationPerParticipant: settings.mobilisationPerParticipant,
    trainingFacilitatorFee:             0,

    breakfast:                  settings.breakfastPerDay,
    lunch:                      settings.lunchPerDay,
    dinner:                     settings.dinnerPerDay,
    accommodation:              settings.accommodationPerNight,
    participantMealsPerSession: settings.participantMealRate,

    clusterMeetingPerParticipant: settings.clusterMeetingParticipantRate,

    ccSelMealsPerParticipant: 0,
    tofPrimaryFeePerSession:  0,
    tofSecondaryFeePerSession: 0,
  };
}

/**
 * Active cost settings re-exported in the legacy shape so existing
 * consumers (the matrix header tooltip, the validation banner, etc.)
 * keep compiling. Numbers come from the engine's CostSettings.
 */
export const ACTIVE_COST_SETTINGS: MfrCostSettingsSnapshot =
  toLegacyCostSnapshot(ENGINE_COST_SETTINGS);

// ────────── Helpers ──────────────────────────────────────────────────

function emptyWeekBuckets(): WeekBuckets {
  return { w1: 0, w2: 0, w3: 0, w4: 0, w5: 0 };
}

function addToWeekBucket(
  buckets: WeekBuckets,
  week: 1 | 2 | 3 | 4 | 5,
  amount: number,
): void {
  const key = `w${week}` as keyof WeekBuckets;
  buckets[key] += amount;
}

function sumBuckets(b: WeekBuckets): number {
  return b.w1 + b.w2 + b.w3 + b.w4 + b.w5;
}

function cell(count: number, total: number): CategoryCell {
  const unitCost = count > 0 ? Math.round(total / count) : 0;
  return { count, unitCost, total };
}

// Map an engine BudgetLine onto the legacy category column it belongs
// in on a staff row. Trainings and cluster meetings get their own
// columns; partner-led activities stay on partner rows.
type StaffColumn =
  | "staffVisits"
  | "partnerVisits"
  | "ssa"
  | "clusterTraining"
  | "groupTrainings";

function staffColumnFor(kind: BudgetLine["kind"]): StaffColumn | "meals_only" {
  switch (kind) {
    case "ssa_visit":
      return "ssa";
    case "cluster_meeting":
    case "cluster_training":
      return "clusterTraining";
    case "training":
    case "core_training":
    case "school_improvement_training":
    case "special_project":
      return "groupTrainings";
    case "staff_visit":
    case "follow_up_visit":
    case "coaching_visit":
    case "core_visit":
      return "staffVisits";
    default:
      return "meals_only";
  }
}

function lineWeekOf(line: BudgetLine): 1 | 2 | 3 | 4 | 5 {
  const w = line.plannedWeek;
  if (w === 1 || w === 2 || w === 3 || w === 4 || w === 5) return w;
  return 1;
}

function sourceCategoryFor(kind: BudgetLine["kind"]): MfrActivityCategory {
  switch (kind) {
    case "ssa_visit":
      return "SSA";
    case "cluster_meeting":
    case "cluster_training":
      return "ClusterTraining";
    case "training":
    case "core_training":
    case "school_improvement_training":
    case "special_project":
      return "GroupTrainings";
    case "partner_visit":
    case "partner_follow_up":
    case "partner_in_school_activity":
      return "PartnerVisits";
    case "staff_visit":
    case "follow_up_visit":
    case "coaching_visit":
    case "core_visit":
    default:
      return "StaffVisits";
  }
}

function sourceTypeFor(
  kind: BudgetLine["kind"],
): MfrSourceRecord["sourceType"] {
  switch (kind) {
    case "cluster_meeting":
      return "PlannedClusterMeeting";
    case "training":
    case "core_training":
    case "school_improvement_training":
    case "cluster_training":
    case "special_project":
      return "PlannedTraining";
    case "ssa_visit":
      return "PlannedSsaActivity";
    case "partner_visit":
    case "partner_follow_up":
    case "partner_in_school_activity":
      return "PlannedPartnerActivity";
    default:
      return "PlannedSchoolVisit";
  }
}

// ────────── BudgetLine → MfrLine aggregation ─────────────────────────

// Activity-summary tally — kept on every accumulator so the
// Particulars column can carry a natural-language summary of the
// month's planned work for the row (instead of the static
// comma-joined kind labels we used to ship).
type ActivitySummaryTally = {
  // Counts by friendly activity name (e.g. "school visit", "cluster
  // training"). Pluralised at render time.
  kindCounts:    Map<string, number>;
  // Districts touched + their type relative to the staff's primary.
  districts:     Map<string, "PRIMARY" | "SECONDARY" | "NA">;
  // Distinct schools — included in the summary tail when meaningful.
  schoolNames:   Set<string>;
};

function emptyActivityTally(): ActivitySummaryTally {
  return {
    kindCounts:  new Map(),
    districts:   new Map(),
    schoolNames: new Set(),
  };
}

type StaffAccumulator = {
  staffId: string;
  staffName: string;
  staffRole: string;
  team: string;
  region: string;
  activityTally: ActivitySummaryTally;
  // Category counts + totals
  staffVisitsCount: number;     staffVisitsTotal: number;
  partnerVisitsCount: number;   partnerVisitsTotal: number;
  ssaCount: number;             ssaTotal: number;
  clusterCount: number;         clusterTotal: number;
  groupTrainingsCount: number;  groupTrainingsTotal: number;
  mealsByWeek: WeekBuckets;
  transportAllocation: number;
  accommodationAllocation: number;
  sourceIds: string[];
};

type PartnerAccumulator = {
  team: string;
  region: string;
  partnerNames: Set<string>;
  partnerVisitsCount: number;
  partnerVisitsTotal: number;
  activityTally: ActivitySummaryTally;
  sourceIds: string[];
};

type SpecialAccumulator = {
  team: string;
  region: string;
  groupTrainingsCount: number;
  groupTrainingsTotal: number;
  activityTally: ActivitySummaryTally;
  sourceIds: string[];
};

function ensureStaff(
  acc: Map<string, StaffAccumulator>,
  staffId: string,
): StaffAccumulator {
  const existing = acc.get(staffId);
  if (existing) return existing;
  const profile = getStaffProfile(staffId);
  const fresh: StaffAccumulator = {
    staffId,
    staffName: profile?.staffName ?? staffId,
    staffRole: profile?.role ?? "CCEO",
    team:      profile?.team   ? `Team ${profile.team}` : "Team Unassigned",
    region:    profile?.region ?? "—",
    activityTally: emptyActivityTally(),
    staffVisitsCount: 0,     staffVisitsTotal: 0,
    partnerVisitsCount: 0,   partnerVisitsTotal: 0,
    ssaCount: 0,             ssaTotal: 0,
    clusterCount: 0,         clusterTotal: 0,
    groupTrainingsCount: 0,  groupTrainingsTotal: 0,
    mealsByWeek: emptyWeekBuckets(),
    transportAllocation: 0,
    accommodationAllocation: 0,
    sourceIds: [],
  };
  acc.set(staffId, fresh);
  return fresh;
}

// ────────── Activity summary generator ───────────────────────────────
//
// Produces a natural-language Particulars string from the engine's
// BudgetLines for a given row. Example outputs:
//
//   "3 school visits + 1 SSA + 2 cluster trainings · Kitgum (P), Pader (S)"
//   "5 cluster trainings + 1 group training · Lira (P)"
//   "6 partner-led visits across 4 partners · Mbale, Tororo +1"
//
// Strategy: rank kinds by count, take the top 3, then a district tail
// with primary/secondary marker for the staff's home district. Caps at
// ~85 chars so the matrix column doesn't wrap into three lines.

const FRIENDLY_KIND: Record<string, { single: string; plural: string }> = {
  staff_visit:                    { single: "school visit",      plural: "school visits"     },
  follow_up_visit:                { single: "follow-up",         plural: "follow-ups"        },
  coaching_visit:                 { single: "coaching visit",    plural: "coaching visits"   },
  ssa_visit:                      { single: "SSA activity",      plural: "SSA activities"    },
  core_visit:                     { single: "core visit",        plural: "core visits"       },
  cluster_meeting:                { single: "cluster meeting",   plural: "cluster meetings"  },
  cluster_training:               { single: "cluster training",  plural: "cluster trainings" },
  training:                       { single: "training",          plural: "trainings"         },
  core_training:                  { single: "core training",     plural: "core trainings"    },
  school_improvement_training:    { single: "SIT session",       plural: "SIT sessions"      },
  special_project:                { single: "ToT session",       plural: "ToT sessions"      },
  partner_visit:                  { single: "partner-led visit", plural: "partner-led visits"},
  partner_follow_up:              { single: "partner follow-up", plural: "partner follow-ups"},
  partner_in_school_activity:     { single: "partner in-school", plural: "partner in-school activities" },
};

function bumpActivityTally(
  tally: ActivitySummaryTally,
  line: BudgetLine,
): void {
  const friendly = FRIENDLY_KIND[line.kind];
  if (friendly) {
    const key = friendly.single;
    tally.kindCounts.set(key, (tally.kindCounts.get(key) ?? 0) + 1);
  }
  if (line.districtName && line.districtType !== "NA") {
    tally.districts.set(line.districtName, line.districtType);
  }
}

function buildActivitySummary(
  tally: ActivitySummaryTally,
  fallback: string,
): string {
  // 1. Activity section: top-3 kinds by count
  const sortedKinds = Array.from(tally.kindCounts.entries())
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);

  if (sortedKinds.length === 0) return fallback;

  const top = sortedKinds.slice(0, 3);
  const activityPart = top
    .map(([kind, n]) => {
      const friendly = Object.values(FRIENDLY_KIND).find((f) => f.single === kind);
      const label = n > 1 ? (friendly?.plural ?? `${kind}s`) : kind;
      return `${n} ${label}`;
    })
    .join(" + ");
  const more = sortedKinds.length > 3 ? ` +${sortedKinds.length - 3} more` : "";

  // 2. District tail: up to 2 districts with (P)/(S) marker
  let districtPart = "";
  if (tally.districts.size > 0) {
    const districts = Array.from(tally.districts.entries()).slice(0, 2);
    const formatted = districts
      .map(([name, type]) => `${name}${type === "PRIMARY" ? " (P)" : type === "SECONDARY" ? " (S)" : ""}`)
      .join(", ");
    const extra = tally.districts.size > 2 ? ` +${tally.districts.size - 2}` : "";
    districtPart = ` · ${formatted}${extra}`;
  }

  return `${activityPart}${more}${districtPart}`;
}

function particularLabelFor(kind: BudgetLine["kind"]): string {
  switch (kind) {
    case "staff_visit":          return "Client school coaching visits";
    case "follow_up_visit":      return "Post-training follow-up visits";
    case "coaching_visit":       return "Coaching visits";
    case "ssa_visit":            return "SSA support activities";
    case "core_visit":           return "Core school visits";
    case "cluster_meeting":      return "Cluster meetings";
    case "cluster_training":     return "Cluster trainings";
    case "training":             return "Group trainings";
    case "core_training":        return "Core trainings";
    case "school_improvement_training": return "School improvement trainings";
    case "special_project":      return "Special project sessions";
    default:                     return "";
  }
}

// ────────── Validation issue extraction ──────────────────────────────

function buildValidationIssues(rollup: BudgetRollup): MfrValidationIssue[] {
  const issues: MfrValidationIssue[] = [];
  let idx = 0;
  for (const line of rollup.lines) {
    if (line.status === "Incomplete") {
      idx += 1;
      issues.push({
        id: `vi-incomplete-${idx}`,
        severity: "warning",
        code: "MISSING_PARTICIPANT_COUNT",
        message:
          line.statusReason ??
          `Activity ${line.activityId} is missing required data — please complete the plan.`,
        sourceActivityId: line.activityId,
      });
    } else if (line.status === "Blocked") {
      idx += 1;
      issues.push({
        id: `vi-blocked-${idx}`,
        severity: "critical",
        code: "MISSING_STAFF_PRIMARY_DISTRICT",
        message:
          line.statusReason ??
          `Activity ${line.activityId} cannot be budgeted — staff profile is incomplete.`,
        sourceActivityId: line.activityId,
      });
    }
  }
  return issues;
}

// ────────── Approval history seed ────────────────────────────────────

function seededApprovalHistory(fundRequestId: string): MfrApprovalEvent[] {
  return [
    { id: "ev-1", fundRequestId, fromStatus: "—",              toStatus: "AUTO_GENERATED", actorRole: "System",      actorId: "system",     actorName: "Edify System",     at: "2026-03-29T06:00:00Z", note: "Built from approved monthly plans" },
    { id: "ev-2", fundRequestId, fromStatus: "AUTO_GENERATED", toStatus: "UNDER_PL_REVIEW", actorRole: "ProgramLead", actorId: "STF-PL-001", actorName: "Patrick Kibirige", at: "2026-03-29T08:21:00Z", note: "Opened for review" },
  ];
}

// ────────── Admin items echo ─────────────────────────────────────────
//
// We send SEEDED_ADMIN_ITEMS through the engine for its rollup-side
// effects, then re-expose them here as MfrAdminItem rows so the UI
// admin grid renders untouched.

function buildAdminItems(fundRequestId: string): MfrAdminItem[] {
  const cdId   = "STF-CD-001";
  const cdName = "Christine Atim";
  let i = 0;
  return effectiveAdminItems().map((s) => {
    i += 1;
    return {
      id:            s.id,
      fundRequestId,
      category:      s.category,
      itemName:      s.name,
      quantity:      s.quantity,
      unitCost:      s.unitCost,
      totalCost:     s.quantity * s.unitCost,
      week:          s.week,
      justification: s.justification,
      addedByCdId:   cdId,
      addedByCdName: cdName,
      createdAt:     `2026-03-30T10:0${i}:00Z`,
    };
  });
}

// ────────── Entry point ──────────────────────────────────────────────

export function generateMonthlyFundRequest(opts?: {
  /** Override the initial status to mirror a particular role's view. */
  status?: MonthlyFundRequest["status"];
}): MonthlyFundRequest {
  const fundRequestId = "mfr-2026-04-uganda";
  const monthIso      = "2026-04";
  const countryId     = "uganda";

  // 1. Pull planned activities + run the engine.
  const activities: PlannedActivity[] = getPlannedActivities({
    monthIso,
    countryId,
  });

  const rollup: BudgetRollup = generateBudget({
    countryId,
    monthIso,
    activities,
    settings: ENGINE_COST_SETTINGS,
    adminItems: effectiveAdminItems().map((s) => ({
      id:       s.id,
      quantity: s.quantity,
      unitCost: s.unitCost,
      week:     s.week,
      name:     s.name,
    })),
  });

  // 2. Bucket engine lines into per-staff, per-partner, special-project
  //    accumulators. Each accumulator becomes one MfrLine.
  const staffAcc   = new Map<string, StaffAccumulator>();
  const partnerAcc = new Map<string, PartnerAccumulator>();
  const specialAcc = new Map<string, SpecialAccumulator>();
  const sources: MfrSourceRecord[] = [];
  const adminLineIds = new Set(effectiveAdminItems().map((s) => s.id));

  for (const line of rollup.lines) {
    // Admin lines are handled separately via SEEDED_ADMIN_ITEMS echo.
    if (adminLineIds.has(line.activityId)) continue;

    const total = line.total;
    if (line.kind === "special_project") {
      const key = "special-projects";
      const existing = specialAcc.get(key) ?? {
        team: "Special Projects",
        region: "Country",
        groupTrainingsCount: 0,
        groupTrainingsTotal: 0,
        activityTally: emptyActivityTally(),
        sourceIds: [],
      };
      existing.groupTrainingsCount += 1;
      existing.groupTrainingsTotal += total;
      bumpActivityTally(existing.activityTally, line);
      const sourceId = `mfr-src-${line.activityId}`;
      existing.sourceIds.push(sourceId);
      specialAcc.set(key, existing);
      sources.push({
        id: sourceId,
        fundRequestId,
        lineId: `mfr-sp-tots`,
        sourceType: sourceTypeFor(line.kind),
        sourceId: line.activityId,
        plannedWeek: lineWeekOf(line),
        amount: total,
        costCategory: sourceCategoryFor(line.kind),
        description: `${particularLabelFor(line.kind)} (engine line ${line.activityId})`,
      });
      continue;
    }

    if (line.deliveryOwner === "PARTNER") {
      const profile = line.staffId ? getStaffProfile(line.staffId) : undefined;
      const region  = profile?.region ?? "Country";
      const team    = profile?.team ? `Team ${profile.team}` : "Partners";
      const key = `${team}::${region}`;
      const existing = partnerAcc.get(key) ?? {
        team,
        region,
        partnerNames: new Set<string>(),
        partnerVisitsCount: 0,
        partnerVisitsTotal: 0,
        activityTally: emptyActivityTally(),
        sourceIds: [],
      };
      existing.partnerVisitsCount += 1;
      existing.partnerVisitsTotal += total;
      if (line.partnerId) existing.partnerNames.add(line.partnerId);
      bumpActivityTally(existing.activityTally, line);
      const lineId  = `mfr-partner-${region.replace(/\s+/g, "-").toLowerCase()}`;
      const sourceId = `mfr-src-${line.activityId}`;
      existing.sourceIds.push(sourceId);
      partnerAcc.set(key, existing);
      sources.push({
        id: sourceId,
        fundRequestId,
        lineId,
        sourceType: sourceTypeFor(line.kind),
        sourceId: line.activityId,
        plannedWeek: lineWeekOf(line),
        partnerId: line.partnerId,
        partnerName: line.partnerId,
        district: line.districtName,
        amount: total,
        costCategory: sourceCategoryFor(line.kind),
        description: `${particularLabelFor(line.kind)} — ${line.districtName}`,
      });
      continue;
    }

    // Staff-led line.
    const staffId = line.staffId ?? "STF-UNKNOWN";
    const acc = ensureStaff(staffAcc, staffId);
    const column = staffColumnFor(line.kind);
    const label  = particularLabelFor(line.kind);
    bumpActivityTally(acc.activityTally, line);

    const categoryTotal =
      line.transport     +
      line.breakfast     +
      line.lunch         +
      line.dinner        +
      line.accommodation +
      line.sessionFee    +
      line.venueFee      +
      line.participantMeals +
      line.mobilisation  +
      line.partnerLumpSum +
      line.other;

    // Split the line's total between its "category column" (the
    // visit / training column you click on) and its meals / transport
    // / accommodation sidecars. We keep meals on the weekly grid and
    // transport / accommodation separate so the existing UI math
    // works as-is.
    const mealAmount =
      line.breakfast + line.lunch + line.dinner + line.participantMeals;
    addToWeekBucket(acc.mealsByWeek, lineWeekOf(line), mealAmount);
    acc.transportAllocation     += line.transport;
    acc.accommodationAllocation += line.accommodation;

    // The "column total" is whatever isn't meals/transport/accommodation
    // so the MfrLine totals reconcile back to BudgetLine.total.
    const columnAmount =
      line.sessionFee + line.venueFee + line.mobilisation +
      line.partnerLumpSum + line.other;

    // Fallback: if all engine sub-fields are zero but total isn't,
    // park the residual on the category column so it still appears.
    const residual = categoryTotal === 0 ? line.total : 0;
    const columnTotal = columnAmount + residual;

    switch (column) {
      case "staffVisits":
        acc.staffVisitsCount += 1;
        acc.staffVisitsTotal += columnTotal;
        break;
      case "partnerVisits":
        acc.partnerVisitsCount += 1;
        acc.partnerVisitsTotal += columnTotal;
        break;
      case "ssa":
        acc.ssaCount += 1;
        acc.ssaTotal += columnTotal;
        break;
      case "clusterTraining":
        acc.clusterCount += 1;
        acc.clusterTotal += columnTotal;
        break;
      case "groupTrainings":
        acc.groupTrainingsCount += 1;
        acc.groupTrainingsTotal += columnTotal;
        break;
      case "meals_only":
      default:
        // meal/transport-only line — already accounted for above
        break;
    }

    const sourceId = `mfr-src-${line.activityId}`;
    acc.sourceIds.push(sourceId);
    sources.push({
      id: sourceId,
      fundRequestId,
      lineId: `mfr-line-${staffId}`,
      sourceType: sourceTypeFor(line.kind),
      sourceId: line.activityId,
      plannedWeek: lineWeekOf(line),
      staffId,
      staffName: acc.staffName,
      district: line.districtName,
      amount: line.total,
      costCategory: sourceCategoryFor(line.kind),
      description: `${label || "Activity"} — ${line.districtName} (W${lineWeekOf(line)})`,
    });
  }

  // 3. Build MfrLine[] from accumulators.
  const lines: MfrLine[] = [];

  for (const acc of staffAcc.values()) {
    const mealsTotal = sumBuckets(acc.mealsByWeek);
    const totalMonthlyAllocation =
      acc.staffVisitsTotal +
      acc.partnerVisitsTotal +
      acc.ssaTotal +
      acc.clusterTotal +
      acc.groupTrainingsTotal +
      mealsTotal +
      acc.transportAllocation +
      acc.accommodationAllocation;

    lines.push({
      id: `mfr-line-${acc.staffId}`,
      fundRequestId,
      kind: "staff",
      team: acc.team,
      region: acc.region,
      staffId: acc.staffId,
      staffName: acc.staffName,
      staffRole: acc.staffRole,
      particulars: buildActivitySummary(
        acc.activityTally,
        "No planned activities for this month",
      ),
      staffVisits:     cell(acc.staffVisitsCount,    acc.staffVisitsTotal),
      partnerVisits:   cell(acc.partnerVisitsCount,  acc.partnerVisitsTotal),
      ssa:             cell(acc.ssaCount,            acc.ssaTotal),
      clusterTraining: cell(acc.clusterCount,        acc.clusterTotal),
      groupTrainings:  cell(acc.groupTrainingsCount, acc.groupTrainingsTotal),
      mealsByWeek: acc.mealsByWeek,
      mealsTotal,
      transportAllocation:     acc.transportAllocation,
      accommodationAllocation: acc.accommodationAllocation,
      totalMonthlyAllocation,
      sourceActivityIds: acc.sourceIds,
      calculationMethod: `Auto-generated from approved monthly plan; rates from ${ENGINE_COST_SETTINGS.versionId}.`,
    });
  }

  for (const acc of partnerAcc.values()) {
    const partnerCount = acc.partnerNames.size;
    lines.push({
      id: `mfr-partner-${acc.region.replace(/\s+/g, "-").toLowerCase()}`,
      fundRequestId,
      kind: "partner",
      team: "Partners",
      region: acc.region,
      partnerName: `${acc.region} Partner Cohort`,
      particulars: buildActivitySummary(
        acc.activityTally,
        `${partnerCount} active partner${partnerCount === 1 ? "" : "s"} — pooled allocation`,
      ),
      staffVisits:     cell(0, 0),
      partnerVisits:   cell(acc.partnerVisitsCount, acc.partnerVisitsTotal),
      ssa:             cell(0, 0),
      clusterTraining: cell(0, 0),
      groupTrainings:  cell(0, 0),
      mealsByWeek: emptyWeekBuckets(),
      mealsTotal: 0,
      transportAllocation: 0,
      accommodationAllocation: 0,
      totalMonthlyAllocation: acc.partnerVisitsTotal,
      sourceActivityIds: acc.sourceIds,
      calculationMethod: "Partner lump-sum × planned partner visits.",
    });
  }

  for (const acc of specialAcc.values()) {
    lines.push({
      id: `mfr-sp-tots`,
      fundRequestId,
      kind: "special_project",
      team: "Special Projects",
      region: acc.region,
      particulars: buildActivitySummary(
        acc.activityTally,
        "Special project facilitation",
      ),
      staffVisits:     cell(0, 0),
      partnerVisits:   cell(0, 0),
      ssa:             cell(0, 0),
      clusterTraining: cell(0, 0),
      groupTrainings:  cell(acc.groupTrainingsCount, acc.groupTrainingsTotal),
      mealsByWeek: emptyWeekBuckets(),
      mealsTotal: 0,
      transportAllocation: 0,
      accommodationAllocation: 0,
      totalMonthlyAllocation: acc.groupTrainingsTotal,
      sourceActivityIds: acc.sourceIds,
      calculationMethod: "Special project — engine training calculator applied.",
    });
  }

  // 4. Admin items — echo SEEDED_ADMIN_ITEMS straight onto the request.
  //    (The engine already accounted for them in its rollup; we only
  //    need the UI-visible MfrAdminItem rows here.)
  const adminItems = buildAdminItems(fundRequestId);

  // Touch calculateAdminBudget once to keep the import live and prove
  // the per-item math reconciles — no-op for the UI.
  void calculateAdminBudget;

  // 5. Totals.
  const totalProgramCost = lines.reduce((s, l) => s + l.totalMonthlyAllocation, 0);
  const totalAdminCost   = adminItems.reduce((s, a) => s + a.totalCost, 0);
  const grandTotal       = totalProgramCost + totalAdminCost;

  // 6. Validation — surface engine Incomplete/Blocked statuses.
  const validationIssues = buildValidationIssues(rollup);

  return {
    id:                  fundRequestId,
    monthLabel:          "April 2026",
    monthIso,
    quarter:             "Q1",
    fyLabel:             rollup.fyLabel,
    countryId,
    countryName:         "Uganda",
    programLeadId:       "STF-PL-001",
    programLeadName:     "Patrick Kibirige",
    countryDirectorId:   "STF-CD-001",
    countryDirectorName: "Christine Atim",
    rvpId:               "STF-RVP-001",
    rvpName:             "Daniel Mwesigwa",

    status: opts?.status ?? "UNDER_PL_REVIEW",

    generatedFromIso: "2026-04-01",
    generatedToIso:   "2026-04-30",
    generatedAtIso:   "2026-03-29T06:00:00Z",
    generatedByName:  "Edify System",

    totalProgramCost: { amount: totalProgramCost, currency: "UGX" },
    totalAdminCost:   { amount: totalAdminCost,   currency: "UGX" },
    grandTotal:       { amount: grandTotal,       currency: "UGX" },

    lines,
    adminItems,
    sources,
    approvalHistory: seededApprovalHistory(fundRequestId),
    validationIssues,
    costSettings: toLegacyCostSnapshot(rollup.costSettings),
  };
}

// Singleton export for the page (server can also call generate() with
// different status overrides per role).
export const currentMonthlyFundRequest = generateMonthlyFundRequest();
