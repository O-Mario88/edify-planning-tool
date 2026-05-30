// All operational rates that drive the budget engine.
// Frozen with each generated request so historical re-renders stay reproducible.

export type CostSettings = {
  versionId: string;
  fyLabel: string;
  capturedAtIso: string;
  countryId: string;
  staffPrimaryTransportPerSchool: number;
  staffSecondaryTransportPerSchool: number;
  breakfastPerDay: number;
  lunchPerDay: number;
  dinnerPerDay: number;
  accommodationPerNight: number;
  partnerVisitLumpSum: number;
  trainingSessionFee: number;
  trainingVenueFee: number;
  participantMealRate: number;
  mobilisationPerParticipant: number;
  clusterMeetingParticipantRate: number;
};

export const ACTIVE_COST_SETTINGS: CostSettings = {
  versionId: "cs-v4.0-fy26",
  fyLabel: "FY 2026",
  capturedAtIso: "2026-04-01",
  countryId: "uganda",
  staffPrimaryTransportPerSchool: 50000,
  staffSecondaryTransportPerSchool: 66000,
  breakfastPerDay: 20000,
  lunchPerDay: 30000,
  dinnerPerDay: 50000,
  accommodationPerNight: 150000,
  partnerVisitLumpSum: 40000,
  trainingSessionFee: 200000,
  trainingVenueFee: 50000,
  participantMealRate: 10000,
  mobilisationPerParticipant: 2000,
  clusterMeetingParticipantRate: 10000,
};

export function getActiveCostSettings(countryId: string): CostSettings {
  if (countryId !== ACTIVE_COST_SETTINGS.countryId) {
    throw new Error(
      `No active cost settings registered for countryId="${countryId}". ` +
        `Available: "${ACTIVE_COST_SETTINGS.countryId}".`,
    );
  }
  return ACTIVE_COST_SETTINGS;
}

export function frozenSnapshot(settings: CostSettings): CostSettings {
  return Object.freeze({ ...settings });
}
