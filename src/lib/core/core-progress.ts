// Core plan progress engine — derives the 4-visits + 4-trainings package state
// from the activity slots. Single source for "how far is this core plan" and
// "is it ready for follow-up SSA".

import "server-only";
import { slotsForPlan } from "./core-store";
import { VISITS_TARGET, TRAININGS_TARGET, type CoreActivitySlot } from "./core-types";

export type NextRequired = {
  slotId: string;
  activityType: "visit" | "training";
  sequenceNumber: number;
  intervention: string;
};

export type CorePlanProgress = {
  visitsCompleted: number;
  trainingsCompleted: number;
  totalCompleted: number;
  packageCompletionPercent: number;
  nextRequired?: NextRequired;
  pendingIA: number;
  pendingEvidence: number;
  pendingSalesforceId: number;
  pendingPayment: number;
  returnedOrRejected: number;
  readyForFollowUpSSA: boolean;
};

const DONE = "Completed";

export function corePlanProgress(planId: string): CorePlanProgress {
  const slots = slotsForPlan(planId);
  const visits = slots.filter((s) => s.activityType === "visit");
  const trainings = slots.filter((s) => s.activityType === "training");

  const visitsCompleted = visits.filter((s) => s.status === DONE).length;
  const trainingsCompleted = trainings.filter((s) => s.status === DONE).length;
  const totalCompleted = visitsCompleted + trainingsCompleted;

  const pendingIA = slots.filter((s) => s.status === "Awaiting IA Verification").length;
  const pendingSalesforceId = slots.filter((s) => s.status === "Salesforce ID Required" || s.status === "Evidence Uploaded").length;
  const pendingEvidence = slots.filter((s) => s.status === "In Progress").length;
  const pendingPayment = slots.filter((s) => s.status === "IA Verified" && !!s.assignedPartnerId).length;
  const returnedOrRejected = slots.filter((s) => s.status === "Returned" || s.status === "Rejected").length;

  // Next required = first incomplete slot, visits before trainings, by sequence.
  const incomplete = [...slots]
    .filter((s) => s.status !== DONE)
    .sort((a, b) => (a.activityType === b.activityType ? a.sequenceNumber - b.sequenceNumber : a.activityType === "visit" ? -1 : 1));
  const n = incomplete[0];
  const nextRequired: NextRequired | undefined = n
    ? { slotId: n.id, activityType: n.activityType, sequenceNumber: n.sequenceNumber, intervention: n.intervention }
    : undefined;

  const allIaVerified = slots.every((s) => s.status === DONE);
  const readyForFollowUpSSA =
    visitsCompleted >= VISITS_TARGET &&
    trainingsCompleted >= TRAININGS_TARGET &&
    returnedOrRejected === 0 &&
    allIaVerified;

  return {
    visitsCompleted,
    trainingsCompleted,
    totalCompleted,
    packageCompletionPercent: Math.round((totalCompleted / (VISITS_TARGET + TRAININGS_TARGET)) * 100),
    nextRequired,
    pendingIA,
    pendingEvidence,
    pendingSalesforceId,
    pendingPayment,
    returnedOrRejected,
    readyForFollowUpSSA,
  };
}

/** Recompute a plan's cached counters from its slots (called after a slot mutates). */
export function recomputePlanCounters(slots: CoreActivitySlot[]): { visitsCompleted: number; trainingsCompleted: number; packageCompletionPercent: number } {
  const visitsCompleted = slots.filter((s) => s.activityType === "visit" && s.status === DONE).length;
  const trainingsCompleted = slots.filter((s) => s.activityType === "training" && s.status === DONE).length;
  return {
    visitsCompleted,
    trainingsCompleted,
    packageCompletionPercent: Math.round(((visitsCompleted + trainingsCompleted) / (VISITS_TARGET + TRAININGS_TARGET)) * 100),
  };
}
