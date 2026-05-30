// Server-side helper — resolves canonical VisitCostRates +
// GroupActivityRates from the country cost settings. Importing this
// file pulls in cost-settings-mock (which is server-only), so call it
// from server components / route handlers, never from client code.

import "server-only";
import { activeCostFor } from "@/lib/cost-settings-mock";
import type { VisitCostRates, GroupActivityRates } from "./cost-engine";

export function loadVisitCostRates(): VisitCostRates {
  return {
    staffPrimaryTransportPerSchool:   activeCostFor("Staff Commuting Transport"),
    staffSecondaryTransportPerSchool: activeCostFor("Staff Overnight Transport"),
    staffLunchPerDay:                 activeCostFor("Lunch Per Day"),
    staffBreakfastPerDay:             activeCostFor("Breakfast Per Day"),
    staffDinnerPerDay:                activeCostFor("Dinner Per Day"),
    staffAccommodationPerNight:       activeCostFor("Accommodation Per Night"),
    partnerLumpSumPerSchool:          activeCostFor("Partner Visit Cost Per School"),
  };
}

export function loadGroupActivityRates(): GroupActivityRates {
  return {
    trainingSessionFee:                  activeCostFor("Training Session Fee"),
    trainingVenueFee:                    activeCostFor("Venue Fee"),
    trainingParticipantMeals:            activeCostFor("Training Participant Meals"),
    trainingMobilisationPerParticipant:  activeCostFor("Training Mobilisation Per Participant"),
    clusterMeetingPerParticipant:        activeCostFor("Cluster Meeting Cost Per Participant"),
  };
}
