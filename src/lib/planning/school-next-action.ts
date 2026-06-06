// Shared resolver for the "Plan Action" button (spec §5). Given a school's
// cluster / SSA / type status, decide the ONE correct next workflow — so every
// surface that shows "Plan Action" routes to the same place instead of a generic
// /planning page. Pure + shape-agnostic so it works over mock rows OR the backend
// school record (both expose clusterStatus / currentFySsaStatus / schoolType).

export type SchoolActionType =
  | "ADD_TO_CLUSTER"
  | "SCHEDULE_SIT" // SSA activation (school improvement training / assign SSA / schedule SSA)
  | "PLAN_RECOMMENDED" // client school with SSA → recommended visit/training
  | "PLAN_CORE_PACKAGE" // core school with SSA → 4 visits + 4 trainings
  | "VIEW_ONLY";

export type SchoolBlockingGate = "NO_CLUSTER" | "NO_CURRENT_FY_SSA" | null;

/** The intent param appended to /schools/[id] so the profile opens the right section. */
export type SchoolView = "cluster" | "ssa" | "plan" | "core";

export type SchoolStatusInput = {
  clusterStatus?: string | null; // "clustered" | "unclustered" | "needs_review"
  currentFySsaStatus?: string | null; // "done" | "not_done" | "scheduled" | "partner_assigned"
  schoolType?: string | null; // "core" | "client" | "potential_core"
  hasActiveProject?: boolean;
};

export type SchoolNextAction = {
  actionType: SchoolActionType;
  blockingGate: SchoolBlockingGate;
  view: SchoolView;
  label: string;
  reason: string;
};

const isClustered = (s: SchoolStatusInput) =>
  (s.clusterStatus ?? "").toLowerCase() === "clustered";
const ssaDone = (s: SchoolStatusInput) =>
  (s.currentFySsaStatus ?? "").toLowerCase() === "done";
const isCore = (s: SchoolStatusInput) =>
  (s.schoolType ?? "").toLowerCase() === "core";

/**
 * Resolve the correct next planning action for a school (spec §4/§5). The gate
 * order is fixed: cluster first, then current-FY SSA, then recommended/core
 * planning. The returned `view` is the deep-link target on /schools/[id].
 */
export function resolveSchoolNextAction(school: SchoolStatusInput): SchoolNextAction {
  if (!isClustered(school)) {
    return {
      actionType: "ADD_TO_CLUSTER",
      blockingGate: "NO_CLUSTER",
      view: "cluster",
      label: "Add to Cluster",
      reason: "School is unclustered — planning is locked until it joins a cluster.",
    };
  }
  if (!ssaDone(school)) {
    return {
      actionType: "SCHEDULE_SIT",
      blockingGate: "NO_CURRENT_FY_SSA",
      view: "ssa",
      label: "Activate SSA",
      reason: "Clustered, but missing this FY's SSA — schedule/assign the SSA to unlock planning.",
    };
  }
  if (isCore(school)) {
    return {
      actionType: "PLAN_CORE_PACKAGE",
      blockingGate: null,
      view: "core",
      label: "Plan Core Package",
      reason: "Core school with current SSA — plan the next item in its 4-visit + 4-training package.",
    };
  }
  return {
    actionType: "PLAN_RECOMMENDED",
    blockingGate: null,
    view: "plan",
    label: "Plan Recommended Support",
    reason: "SSA complete — plan the recommended visit/training for its weakest interventions.",
  };
}

/** The deep link a school action button should use (never a generic page). */
export function schoolActionHref(schoolId: string, view: SchoolView): string {
  return `/schools/${encodeURIComponent(schoolId)}?view=${view}`;
}
