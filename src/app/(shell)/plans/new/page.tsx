import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanBuilderView } from "@/components/mobile/views/PlanBuilderView";
import { PlanBuilderDesktopView } from "@/components/planning/PlanBuilderDesktopView";
import { DistrictGatewayCard } from "@/components/planning/DistrictGatewayCard";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  highPrioritySchoolVisits,
  highPriorityClusters,
  partnerCapacityProfiles,
  generatePartnerFollowUpRecommendations,
  type PartnerFollowUpRecommendation,
} from "@/lib/plan-builder-engine";
import { activeCostFor } from "@/lib/cost-settings-mock";
import { loadVisitCostRates } from "@/lib/cost-engine/cost-engine-server";
import type { PlanCostRates } from "@/lib/plan-cost-calculator";
import { getCurrentUser } from "@/lib/auth";

export default async function PlanBuilderPage() {
  // Read the planner's identity — drives the home-district callout in
  // the district gateway. In production this resolves via StaffHomeBase;
  // for the prototype we hard-code the demo district matching the demo
  // CCEO (Paul Chinyama → Mukono).
  await getCurrentUser(); // ensure session is resolved (guard-gate)
  const homeDistrict = "Mukono";

  // Pre-compute recommendations for every partner so the client view never
  // needs to call the server-only engine on partner change.
  const recommendationsByPartner: Record<string, PartnerFollowUpRecommendation[]> = {};
  for (const p of partnerCapacityProfiles) {
    recommendationsByPartner[p.partnerId] = generatePartnerFollowUpRecommendations(p.partnerId);
  }
  const defaultPartnerId = partnerCapacityProfiles[0]?.partnerId ?? "";

  // Cost engine rates (canonical, CD-set) — passed to the gateway so the
  // breakdown matches what the budget approval engine will see later.
  const visitCostRates = loadVisitCostRates();

  // Resolve active cost rates from the country cost settings — the client
  // computes activity totals from these without re-reading the server-only
  // mock module.
  const costRates: PlanCostRates = {
    staffCommutingTransport:        activeCostFor("Staff Commuting Transport"),
    staffLunch:                     activeCostFor("Staff Lunch"),
    staffOvernightTransport:        activeCostFor("Staff Overnight Transport"),
    breakfastPerDay:                activeCostFor("Breakfast Per Day"),
    lunchPerDay:                    activeCostFor("Lunch Per Day"),
    dinnerPerDay:                   activeCostFor("Dinner Per Day"),
    accommodationPerNight:          activeCostFor("Accommodation Per Night"),
    clusterTrainingPerParticipant:  activeCostFor("Cluster Training Cost Per Participant"),
    clusterMeetingPerParticipant:   activeCostFor("Cluster Meeting Cost Per Participant"),
    venueFee:                       activeCostFor("Venue Fee"),
    facilitationFee:                activeCostFor("Facilitation Fee"),
    partnerVisitCostPerSchool:      activeCostFor("Partner Visit Cost Per School"),
    partnerTrainingFacilitationFee: activeCostFor("Partner Training Facilitation Fee"),
    partnerFacilitatorDailyFee:     activeCostFor("Partner Facilitator Daily Fee"),
  };

  return (
    <>
      {/* Canonical page chrome — first element on every viewport. Replaces
          the old TitleRegister + the PageHeader that used to live inside
          PlanBuilderDesktopView. */}
      <PageHeader
        title="Create / Edit Plan"
        dateLabel="May 2025"
        subtitle="Pre-loaded with the highest-priority work — by SSA, training history, partner capacity, and coverage targets. Plan one activity type at a time: each tab uses its own cost formula from active Country Cost Settings."
        backFallbackHref="/plans"
      />
      {/* Step 1 — District Gateway. On MOBILE it's the first content under the
          page header (so it's gated to mobile here); on DESKTOP it renders
          INSIDE the builder, at the top of the content column (passed as the
          `gateway` slot) — no longer floating above the page chrome. */}
      <div className="md:hidden px-3 sm:px-4 pt-3">
        <DistrictGatewayCard homeDistrict={homeDistrict} rates={visitCostRates} />
      </div>
      <ResponsiveDashboard
        mobile={<PlanBuilderView />}
        desktop={
          <PlanBuilderDesktopView
            highPrioritySchoolVisits={highPrioritySchoolVisits}
            highPriorityClusters={highPriorityClusters}
            partnerCapacityProfiles={partnerCapacityProfiles}
            recommendationsByPartner={recommendationsByPartner}
            defaultPartnerId={defaultPartnerId}
            costRates={costRates}
            gateway={<DistrictGatewayCard homeDistrict={homeDistrict} rates={visitCostRates} />}
          />
        }
      />
    </>
  );
}
