// Planning capacity — the single source of truth for "can I still plan an
// activity for this school, or is it grayed out?" (the plan-as-list model).
//
// Rules (per the operating model):
//   • Client school: ONE visit. Once planned, visit planning is grayed out.
//     Client trainings are planned at the CLUSTER level, not per school.
//   • Core school: 4 visits + 4 trainings. Grayed out only when BOTH quotas
//     are full.
//   • A planned activity may be rescheduled at most RESCHEDULE_SLIP_LIMIT times
//     before it must be escalated/converted (so activities can't slip forever).

export const CLIENT_VISIT_QUOTA = 1;
export const CORE_VISIT_QUOTA = 4;
export const CORE_TRAINING_QUOTA = 4;
/** A planned activity may be moved at most this many times before it must be
 *  escalated or converted (keeps "reschedule" from hiding non-delivery). */
export const RESCHEDULE_SLIP_LIMIT = 3;

export type SchoolPlanningType = "core" | "client";

export type PlanningCapacityInput = {
  schoolType?: string | null; // "core"/"Core" → core; anything else → client
  visitsPlanned: number; // active (non-cancelled) visit-type activities for this school
  trainingsPlanned: number; // active training-type activities for this school
};

export type PlanningCapacity = {
  schoolType: SchoolPlanningType;
  visitsUsed: number;
  visitsAllowed: number;
  trainingsUsed: number;
  trainingsAllowed: number;
  canPlanVisit: boolean;
  canPlanTraining: boolean;
  visitDisabledReason: string | null;
  trainingDisabledReason: string | null;
  /** True when nothing more can be planned for this school — gray it out entirely. */
  fullyPlanned: boolean;
};

export function resolvePlanningCapacity(input: PlanningCapacityInput): PlanningCapacity {
  const isCore = (input.schoolType ?? "").toLowerCase() === "core";
  const schoolType: SchoolPlanningType = isCore ? "core" : "client";

  const visitsAllowed = isCore ? CORE_VISIT_QUOTA : CLIENT_VISIT_QUOTA;
  // Client trainings are a cluster-level activity, not a per-school one.
  const trainingsAllowed = isCore ? CORE_TRAINING_QUOTA : 0;

  const visitsUsed = Math.max(0, input.visitsPlanned);
  const trainingsUsed = Math.max(0, input.trainingsPlanned);

  const canPlanVisit = visitsUsed < visitsAllowed;
  const canPlanTraining = trainingsAllowed > 0 && trainingsUsed < trainingsAllowed;

  const visitDisabledReason = canPlanVisit
    ? null
    : isCore
      ? `All ${CORE_VISIT_QUOTA} core visits are already planned.`
      : "A visit is already planned for this school (client schools get one).";

  const trainingDisabledReason = canPlanTraining
    ? null
    : isCore
      ? `All ${CORE_TRAINING_QUOTA} core trainings are already planned.`
      : "Trainings for client schools are planned from the cluster, not the school.";

  const fullyPlanned = !canPlanVisit && !canPlanTraining;

  return {
    schoolType,
    visitsUsed,
    visitsAllowed,
    trainingsUsed,
    trainingsAllowed,
    canPlanVisit,
    canPlanTraining,
    visitDisabledReason,
    trainingDisabledReason,
    fullyPlanned,
  };
}

// ── Reschedule slip limit ───────────────────────────────────────────

export function canReschedule(rescheduleCount: number): boolean {
  return rescheduleCount < RESCHEDULE_SLIP_LIMIT;
}

/** How many moves remain before this activity hits the slip limit. */
export function reschedulesRemaining(rescheduleCount: number): number {
  return Math.max(0, RESCHEDULE_SLIP_LIMIT - rescheduleCount);
}

// ── Activity-kind classification (store ActivityKind → visit | training) ──

const VISIT_KINDS = new Set([
  "SCHOOL_VISIT", "IN_SCHOOL_COACHING", "SSA_FOLLOW_UP", "LESSON_OBSERVATION",
  "PARTNER_FOLLOW_UP", "COURTESY_VISIT",
]);
const TRAINING_KINDS = new Set([
  "CLUSTER_TRAINING", "TRAINING_FOLLOW_UP", "HANDOVER_MEETING",
]);

export function classifyActivityKind(kind: string): "visit" | "training" | "other" {
  if (VISIT_KINDS.has(kind)) return "visit";
  if (TRAINING_KINDS.has(kind)) return "training";
  return "other";
}
