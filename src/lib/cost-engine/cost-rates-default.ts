// Client-safe default rates.
//
// Mirror of the current "Active" CD-set rates in cost-settings-mock.ts.
// Client components that compute cost breakdowns (PlanScheduleByWeek's
// ActivityDetail panel) read from here so they don't have to drag
// `server-only` imports through the React tree.
//
// In production, these are passed as a prop from the server page (which
// reads the live rates via loadVisitCostRates() + loadGroupActivityRates()).
// Until that wiring lands, the constants below match the canonical CD
// settings so the calculator stays in sync.

import type { VisitCostRates, GroupActivityRates } from "./cost-engine";

export const DEFAULT_VISIT_RATES: VisitCostRates = {
  staffPrimaryTransportPerSchool:   56_000,
  staffSecondaryTransportPerSchool: 66_000,
  staffLunchPerDay:                 30_000,
  staffBreakfastPerDay:             20_000,
  staffDinnerPerDay:                50_000,
  staffAccommodationPerNight:      150_000,
  partnerLumpSumPerSchool:          40_000,
};

export const DEFAULT_GROUP_RATES: GroupActivityRates = {
  trainingSessionFee:                 200_000,
  trainingVenueFee:                    50_000,
  trainingParticipantMeals:            10_000,
  trainingMobilisationPerParticipant:   2_000,
  clusterMeetingPerParticipant:        10_000,
};
