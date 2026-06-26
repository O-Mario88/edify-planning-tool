import { VISITS_TARGET, TRAININGS_TARGET } from './core-interventions';

export type SlotLike = {
  id: string;
  activityType: string;
  sequenceNumber: number;
  intervention: string;
  status: string;
  assignedPartnerId?: string | null;
  iaVerificationStatus?: string | null;
};

const DONE = 'Completed';

export type CorePlanProgressDto = {
  visitsCompleted: number;
  trainingsCompleted: number;
  totalCompleted: number;
  packageCompletionPercent: number;
  nextRequired?: { slotId: string; activityType: string; sequenceNumber: number; intervention: string };
  pendingIA: number;
  pendingEvidence: number;
  pendingSalesforceId: number;
  pendingPayment: number;
  returnedOrRejected: number;
  readyForFollowUpSSA: boolean;
};

export function computePlanProgress(slots: SlotLike[]): CorePlanProgressDto {
  const visits = slots.filter((s) => s.activityType === 'visit');
  const trainings = slots.filter((s) => s.activityType === 'training');
  const visitsCompleted = visits.filter((s) => s.status === DONE).length;
  const trainingsCompleted = trainings.filter((s) => s.status === DONE).length;
  const totalCompleted = visitsCompleted + trainingsCompleted;

  const pendingIA = slots.filter((s) => s.status === 'Awaiting IA Verification').length;
  const pendingSalesforceId = slots.filter((s) => s.status === 'Salesforce ID Required' || s.status === 'Evidence Uploaded').length;
  const pendingEvidence = slots.filter((s) => s.status === 'In Progress').length;
  const pendingPayment = slots.filter((s) => s.status === 'IA Verified' && !!s.assignedPartnerId).length;
  const returnedOrRejected = slots.filter((s) => s.status === 'Returned' || s.status === 'Rejected').length;

  const incomplete = [...slots]
    .filter((s) => s.status !== DONE)
    .sort((a, b) => (a.activityType === b.activityType ? a.sequenceNumber - b.sequenceNumber : a.activityType === 'visit' ? -1 : 1));
  const n = incomplete[0];

  const allDone = slots.length > 0 && slots.every((s) => s.status === DONE);
  const readyForFollowUpSSA =
    visitsCompleted >= VISITS_TARGET &&
    trainingsCompleted >= TRAININGS_TARGET &&
    returnedOrRejected === 0 &&
    allDone;

  return {
    visitsCompleted,
    trainingsCompleted,
    totalCompleted,
    packageCompletionPercent: Math.round((totalCompleted / (VISITS_TARGET + TRAININGS_TARGET)) * 100),
    nextRequired: n
      ? { slotId: n.id, activityType: n.activityType, sequenceNumber: n.sequenceNumber, intervention: n.intervention }
      : undefined,
    pendingIA,
    pendingEvidence,
    pendingSalesforceId,
    pendingPayment,
    returnedOrRejected,
    readyForFollowUpSSA,
  };
}

export function recomputeCounters(slots: SlotLike[]) {
  const visitsCompleted = slots.filter((s) => s.activityType === 'visit' && s.status === DONE).length;
  const trainingsCompleted = slots.filter((s) => s.activityType === 'training' && s.status === DONE).length;
  return {
    visitsCompleted,
    trainingsCompleted,
    packageCompletionPercent: Math.round(((visitsCompleted + trainingsCompleted) / (VISITS_TARGET + TRAININGS_TARGET)) * 100),
  };
}
