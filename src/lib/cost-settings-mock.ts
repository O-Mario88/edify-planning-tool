// Country Cost Settings.
//
// Contract:
//   • Only Country Director (or finance-admin role) may set or approve prices.
//   • If any required cost item is missing for the active FY, budget approval
//     is BLOCKED.
//   • Cost settings are FY-scoped — every FY can have its own pricing.
//   • All prices are in UGX unless otherwise noted.

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";

// ────────── Cost item catalog (required for budget builder) ──────────

export const REQUIRED_COST_ITEMS = [
  "Staff school visit cost",
  "Partner school visit cost",
  "Cluster training cost",
  "In-School coaching cost",
  "Participant meal cost",
  "Partner training fee",
  "SSA support cost",
  "SSA verification cost",
  "MSC story collection cost",
  "Exam result collection cost",
  "Enrollment update cost",
  "Special project session cost",
  "Transport allowance",
  "Venue allowance",
  "Materials cost",
  "Evidence verification cost",
  "Partner travel support",
  // ── Per-activity cost settings (set by CD / Accounts) ──
  "Staff Commuting Transport",
  "Staff Lunch",
  "Staff Overnight Transport",
  "Breakfast Per Day",
  "Lunch Per Day",
  "Dinner Per Day",
  "Accommodation Per Night",
  "Cluster Training Cost Per Participant",
  "Cluster Meeting Cost Per Participant",
  "Venue Fee",
  "Facilitation Fee",
  "Training Session Fee",
  "Training Participant Meals",
  "Training Mobilisation Per Participant",
  "Partner Visit Cost Per School",
  "Partner Training Facilitation Fee",
  "Partner Facilitator Daily Fee",
] as const;

export type CostItem = typeof REQUIRED_COST_ITEMS[number];

export type CountryCostSetting = {
  id:             string;
  country:        string;
  financialYearId:string;
  costItem:       CostItem;
  unitCost:       number;
  currency:       string;
  effectiveFrom:  string;
  effectiveTo?:   string;
  setBy:          string;
  approvedBy?:    string;
  status:         "Draft" | "Active" | "Archived";
  /** Version within this FY — bumped on every rate change. v1 = the
   *  FY-opening rate card. Existing approved plans keep the version
   *  they were approved against. */
  version:        number;
};

/** One audit entry per cost-setting change — the trail the backend
 *  CostSettingAudit table will mirror. Newest first. */
export type CostSettingAuditEntry = {
  id:        string;
  costItem:  CostItem;
  /** e.g. "v1 → v2 · UGX 90,000 → UGX 95,000" or "Created v1 (Draft)". */
  change:    string;
  reason?:   string;
  byName:    string;
  byRole:    "CountryDirector" | "Admin" | "ProgramAccountant";
  at:        string; // ISO date
};

const ACTIVE_FY = activeFinancialYear();

export const countryCostSettings: CountryCostSetting[] = [
  cost("Staff school visit cost",         95_000,  "Sarah Okello", "Active", 2),
  cost("Partner school visit cost",      120_000,  "Sarah Okello", "Active"),
  cost("Cluster training cost",        2_400_000,  "Sarah Okello", "Active"),
  cost("In-School coaching cost",        180_000,  "Sarah Okello", "Active"),
  cost("Participant meal cost",           18_000,  "Sarah Okello", "Active"),
  cost("Partner training fee",         1_600_000,  "Sarah Okello", "Active"),
  cost("SSA support cost",                85_000,  "Sarah Okello", "Active"),
  cost("SSA verification cost",           65_000,  "Sarah Okello", "Active"),
  cost("MSC story collection cost",       40_000,  "Sarah Okello", "Active"),
  cost("Exam result collection cost",     30_000,  "Sarah Okello", "Active"),
  cost("Enrollment update cost",          25_000,  "Sarah Okello", "Active"),
  cost("Special project session cost",   460_000,  "Sarah Okello", "Active"),
  cost("Transport allowance",             35_000,  "Sarah Okello", "Active"),
  cost("Venue allowance",                180_000,  "Sarah Okello", "Active"),
  cost("Materials cost",                  60_000,  "Sarah Okello", "Active"),
  // Two items deliberately left Draft so the readiness check flags them.
  cost("Evidence verification cost",      55_000,  "Moses Tindi",  "Draft"),
  cost("Partner travel support",          90_000,  "Moses Tindi",  "Draft"),
  // ── Per-activity cost settings — CD/Accounts owned, never staff-edited ──
  //
  // Canonical rates set by the Country Director (May 2026). The cost engine
  // (lib/cost-engine) reads these via activeCostFor() and composes them by
  // district type (primary vs secondary):
  //
  //   • Staff visit, primary district   → 56k transport/school + 30k lunch/day
  //   • Staff visit, secondary district → 66k transport/school + 30k lunch
  //                                       + 56k dinner + 150k accommodation
  //                                       per night (auto-included)
  //   • Partner visit                   → 40k lump sum per school
  //
  // Primary vs. secondary is derived from the staff's StaffHomeBase vs. the
  // school's district. The /plans/new gateway surfaces this explicitly so
  // the planner sees what triggers the secondary rates.
  cost("Staff Commuting Transport",        56_000,  "Sarah Okello", "Active"),  // primary district per school
  cost("Staff Lunch",                      30_000,  "Sarah Okello", "Active"),  // legacy alias for Lunch Per Day
  cost("Staff Overnight Transport",        66_000,  "Sarah Okello", "Active"),  // secondary district per school
  cost("Breakfast Per Day",                20_000,  "Sarah Okello", "Active"),  // secondary district only
  cost("Lunch Per Day",                    30_000,  "Sarah Okello", "Active"),
  cost("Dinner Per Day",                   50_000,  "Sarah Okello", "Active"),  // secondary district only
  cost("Accommodation Per Night",         150_000,  "Sarah Okello", "Active"),  // secondary district only
  cost("Cluster Training Cost Per Participant", 12_000, "Sarah Okello", "Active"),  // legacy roll-up = Meals 10k + Mobilisation 2k
  cost("Cluster Meeting Cost Per Participant",  10_000, "Sarah Okello", "Active"),
  cost("Venue Fee",                        50_000,  "Sarah Okello", "Active"),
  cost("Facilitation Fee",                200_000,  "Sarah Okello", "Active"),  // legacy alias for Training Session Fee
  cost("Training Session Fee",            200_000,  "Sarah Okello", "Active"),
  cost("Training Participant Meals",       10_000,  "Sarah Okello", "Active"),  // per participant
  cost("Training Mobilisation Per Participant", 2_000, "Sarah Okello", "Active"),
  cost("Partner Visit Cost Per School",    40_000,  "Sarah Okello", "Active"),
  cost("Partner Training Facilitation Fee",420_000, "Sarah Okello", "Active", 2),
  cost("Partner Facilitator Daily Fee",   180_000,  "Sarah Okello", "Active"),
];

function cost(
  item:    CostItem,
  unit:    number,
  setBy:   string,
  status:  CountryCostSetting["status"],
  version = 1,
): CountryCostSetting {
  return {
    id:              `cs-${slug(item)}-${ACTIVE_FY.id}`,
    country:         "Uganda",
    financialYearId: ACTIVE_FY.id,
    costItem:        item,
    unitCost:        unit,
    currency:        "UGX",
    effectiveFrom:   ACTIVE_FY.startDate,
    setBy,
    approvedBy:      status === "Active" ? "Sarah Okello" : undefined,
    status,
    version,
  };
}

// ── Audit trail ─────────────────────────────────────────────────────
//
// Every cost change in the demo seed, newest first. The page shows this
// under the register so "who changed what rate, when, and why" is one
// glance — no field staff ever invents an activity cost.
export const costSettingAudit: CostSettingAuditEntry[] = [
  {
    id: "ca-7", costItem: "Staff school visit cost",
    change: "v1 → v2 · UGX 90,000 → UGX 95,000",
    reason: "Fuel price adjustment for FY 2026",
    byName: "Sarah Okello", byRole: "CountryDirector", at: "2026-05-20",
  },
  {
    id: "ca-6", costItem: "Partner Training Facilitation Fee",
    change: "v1 → v2 · UGX 400,000 → UGX 420,000",
    reason: "Aligned with signed partner contracts",
    byName: "Sarah Okello", byRole: "CountryDirector", at: "2026-05-18",
  },
  {
    id: "ca-5", costItem: "Accommodation Per Night",
    change: "Created v1 (Active) · UGX 150,000",
    byName: "Sarah Okello", byRole: "CountryDirector", at: "2026-05-12",
  },
  {
    id: "ca-4", costItem: "Evidence verification cost",
    change: "Created v1 (Draft) · UGX 55,000",
    reason: "Awaiting CD approval",
    byName: "Moses Tindi", byRole: "ProgramAccountant", at: "2026-05-10",
  },
  {
    id: "ca-3", costItem: "Partner travel support",
    change: "Created v1 (Draft) · UGX 90,000",
    reason: "Awaiting CD approval",
    byName: "Moses Tindi", byRole: "ProgramAccountant", at: "2026-05-10",
  },
  {
    id: "ca-2", costItem: "Cluster Meeting Cost Per Participant",
    change: "Created v1 (Active) · UGX 10,000",
    byName: "Sarah Okello", byRole: "CountryDirector", at: "2026-05-08",
  },
  {
    id: "ca-1", costItem: "Staff Commuting Transport",
    change: "Created v1 (Active) · UGX 56,000",
    byName: "Sarah Okello", byRole: "CountryDirector", at: "2026-05-08",
  },
];

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// ────────── Lookups ──────────

export function activeCostFor(item: CostItem, fyId: string = ACTIVE_FY.id): number {
  const row = countryCostSettings.find(
    (c) => c.costItem === item && c.financialYearId === fyId && c.status === "Active",
  );
  return row?.unitCost ?? 0;
}

export function missingCostSettings(fyId: string = ACTIVE_FY.id): CostItem[] {
  return REQUIRED_COST_ITEMS.filter(
    (item) => !countryCostSettings.some(
      (c) => c.costItem === item && c.financialYearId === fyId && c.status === "Active",
    ),
  );
}

// validateCountryCostSettings — returns the readiness verdict + missing items.
export function validateCountryCostSettings(fyId: string = ACTIVE_FY.id): {
  ready:   boolean;
  missing: CostItem[];
  active:  number;
  total:   number;
} {
  const missing = missingCostSettings(fyId);
  return {
    ready:   missing.length === 0,
    missing,
    active:  REQUIRED_COST_ITEMS.length - missing.length,
    total:   REQUIRED_COST_ITEMS.length,
  };
}

// ────────── UGX formatter (shared across budget surfaces) ──────────

export function formatUgxBig(value: number): string {
  if (value >= 1_000_000_000) return `UGX ${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000)     return `UGX ${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000)         return `UGX ${(value / 1_000).toFixed(0)}K`;
  return `UGX ${value}`;
}
