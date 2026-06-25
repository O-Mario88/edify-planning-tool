// ── Central CostingService (frontend façade) ────────────────────────────────
//
// Single entry point used by EVERY scheduling drawer in the app. All cost
// lookups for any planned/scheduled activity must go through here — no
// hardcoded UGX, no ad-hoc math in components, no parallel "default rate"
// blocks. The function:
//
//   1. Calls the backend `/budget/costing/preview` when the BFF is enabled
//      (single source of truth = `CostSetting` rows, owned by CD).
//   2. Falls back to the in-memory cost-engine when the backend is off,
//      so demo / mock surfaces don't suddenly show "—".
//   3. Returns a normalized `CostingResult` shape that includes:
//        • totalCost, currency
//        • breakdown lines (label / unit / qty / amount / missing)
//        • catalogueVersion + costCatalogueId (when known)
//        • missingItems list (for the Cost Blocker UI)
//        • canSchedule boolean (false ⇒ Schedule button must be disabled)
//        • costWarnings (non-blocking notices, e.g. "rate older than 90d")
//
// Server-only by design — the BFF token never crosses to the browser.
// Client schedule drawers must call this through a thin server action (or
// the existing `backendCostPreview` surface when authenticated).

import "server-only";

import { backendCostPreview, type BeCostLine, type BeCostPreview } from "@/lib/api/surfaces";
import type { BackendUser } from "@/lib/api/backend";

export type CostingActivityKind =
  | "school_visit"
  | "follow_up_visit"
  | "coaching_visit"
  | "in_school_support"
  | "core_visit"
  | "training"
  | "school_improvement_training"
  | "cluster_training"
  | "core_training"
  | "cluster_meeting"
  | "ssa_activity"
  | "partner_activity"
  | "project_activity";

export type CostingDeliveryMode = "staff" | "partner";

export type CostingInput = {
  /** The unified activity type the backend understands. */
  activityType: CostingActivityKind;
  /** Staff or partner — partner = lump sum, staff = transport + per-diem. */
  deliveryType: CostingDeliveryMode;
  /** "primary" when school district = staff home district, else "secondary". */
  districtType?: "primary" | "secondary";
  /** Trainings + cluster meetings: scheduled participant estimate. */
  expectedParticipants?: number;
  /** Multi-day staff trips: nights stayed (drives accommodation × N). */
  nights?: number;
  /** Project-tagged activity → project-specific rate fallback. */
  projectId?: string;
  /** Actuals — when present, overrides expected and drives the recalc. */
  teachersAttended?: number;
  leadersAttended?: number;
  otherParticipants?: number;
};

export type CostingLine = {
  label: string;
  costSettingKey: string;
  unitCost: number | null;
  quantity: number;
  amount: number;
  missing: boolean;
};

export type CostingResult =
  | {
      ok: true;
      source: "live" | "mock";
      /** Source label e.g. "Uganda · FY2026 Country Cost Register". */
      catalogueLabel: string;
      catalogueVersion: number;
      currency: "UGX";
      totalCost: number;
      lines: CostingLine[];
      /** Empty when fully costable. */
      missingItems: string[];
      /** Schedule button enable signal. */
      canSchedule: boolean;
      /** Non-blocking advisories. */
      costWarnings: string[];
    }
  | {
      ok: false;
      source: "live" | "mock";
      reason: "no_active_catalogue" | "missing_cost_items" | "fetch_failed";
      message: string;
      /** When the failure is missing items, the keys are listed for the UI. */
      missingItems: string[];
      canSchedule: false;
    };

const fromBackendLine = (l: BeCostLine): CostingLine => ({
  label: l.label,
  costSettingKey: l.key,
  unitCost: l.unit,
  quantity: l.qty,
  amount: l.amount,
  missing: l.missing,
});

/** Convert a successful backend preview into the normalized CostingResult. */
function normalizeBackendPreview(p: BeCostPreview): CostingResult {
  const missingItems = p.missingItems ?? p.lines.filter((l) => l.missing).map((l) => l.key);
  const canSchedule = p.canSchedule ?? !p.costMissing;
  if (!canSchedule) {
    return {
      ok: false,
      source: "live",
      reason: "missing_cost_items",
      message: `Catalogue missing: ${missingItems.join(", ")}`,
      missingItems,
      canSchedule: false,
    };
  }
  return {
    ok: true,
    source: "live",
    catalogueLabel: p.source,
    catalogueVersion: p.catalogueVersion ?? 1,
    currency: "UGX",
    totalCost: p.amount,
    lines: p.lines.map(fromBackendLine),
    missingItems,
    canSchedule,
    costWarnings: [],
  };
}

/** The single canonical "calculate cost for an activity" function.
 *  Every scheduling drawer (cluster meeting, cluster training, SIT, school
 *  visit, partner schedule, project activity, reschedule…) calls this. */
export async function calculateActivityCost(
  input: CostingInput,
  user: BackendUser,
): Promise<CostingResult> {
  const res = await backendCostPreview(user, {
    activityType: input.activityType,
    deliveryType: input.deliveryType,
    districtType: input.districtType,
    teachersAttended: input.teachersAttended,
    leadersAttended: input.leadersAttended,
    otherParticipants: input.otherParticipants,
    expectedParticipants: input.expectedParticipants,
    nights: input.nights,
    projectId: input.projectId,
  });
  if (!res.live) {
    return {
      ok: false,
      source: "live",
      reason: "fetch_failed",
      message: res.error ?? "Cost preview unavailable",
      missingItems: [],
      canSchedule: false,
    };
  }
  return normalizeBackendPreview(res.data);
}
