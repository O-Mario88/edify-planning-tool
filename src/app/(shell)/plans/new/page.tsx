import { ClipboardList } from "lucide-react";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanBuilderView } from "@/components/mobile/views/PlanBuilderView";
import { PlanBuilderDesktopView } from "@/components/planning/PlanBuilderDesktopView";
import { DistrictGatewayCard } from "@/components/planning/DistrictGatewayCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import type {
  SchoolVisitRecommendation,
  ClusterRecommendation,
  PartnerCapacityProfile,
  PartnerFollowUpRecommendation,
} from "@/lib/plan-builder-engine";
import { activeCostFor } from "@/lib/cost-settings-mock";
import { loadVisitCostRates } from "@/lib/cost-engine/cost-engine-server";
import type { PlanCostRates } from "@/lib/plan-cost-calculator";
import { getCurrentUser } from "@/lib/auth";
import { isBackendEnabled } from "@/lib/api/backend";
import { isMockAllowed } from "@/lib/mock-policy";
import { backendPlanBuilderBundle } from "@/lib/planning/backend-plan-builder";

export default async function PlanBuilderPage() {
  // Read the planner's identity — drives the home-district callout and the
  // role-scoped live plan-builder feed.
  const user = await getCurrentUser();

  // ── Resolve the recommendation source ──────────────────────────────
  // 1. Backend on → live, role-scoped clustered + current-FY-SSA, not-yet-
  //    planned schools/clusters/partners (the production path).
  // 2. Backend off + mock opted-in (dev only) → the synthetic engine.
  // 3. Otherwise (production, backend unreachable) → an explicit empty state,
  //    NEVER fabricated demo schools.
  const live = isBackendEnabled() ? await backendPlanBuilderBundle(user) : null;
  const useMock = !live && isMockAllowed();

  if (!live && !useMock) {
    return (
      <>
        <PageHeader title="Create / Edit Plan" backFallbackHref="/plans" />
        <div className="px-3 sm:px-4 pt-3">
          <ProductiveEmptyState
            Icon={ClipboardList}
            title="No clustered, SSA-complete schools are ready to plan yet"
            description="The plan builder loads the highest-priority work directly from your portfolio: schools that are clustered, have a current-year SSA, and don't yet have a planned activity. Get schools to that state first."
            actionLabel="Open the planning board"
            actionHref="/planning"
            links={[
              { label: "Assign schools to a cluster", href: "/clusters" },
              { label: "Upload an SSA", href: "/schools" },
            ]}
            note="No placeholder schools or clusters are shown."
          />
        </div>
      </>
    );
  }

  // Resolve the data arrays from the live bundle, or (dev opt-in) the mock
  // engine loaded lazily so its synthetic generators never run in production.
  let highPrioritySchoolVisits: SchoolVisitRecommendation[];
  let highPriorityClusters: ClusterRecommendation[];
  let partnerCapacityProfiles: PartnerCapacityProfile[];
  let recommendationsByPartner: Record<string, PartnerFollowUpRecommendation[]>;
  let defaultPartnerId: string;

  if (live) {
    ({ highPrioritySchoolVisits, highPriorityClusters, partnerCapacityProfiles, recommendationsByPartner, defaultPartnerId } = live);
  } else {
    const mock = await import("@/lib/plan-builder-engine");
    highPrioritySchoolVisits = mock.highPrioritySchoolVisits;
    highPriorityClusters = mock.highPriorityClusters;
    partnerCapacityProfiles = mock.partnerCapacityProfiles;
    recommendationsByPartner = {};
    for (const p of partnerCapacityProfiles) {
      recommendationsByPartner[p.partnerId] = mock.generatePartnerFollowUpRecommendations(p.partnerId);
    }
    defaultPartnerId = partnerCapacityProfiles[0]?.partnerId ?? "";
  }

  // Home district for the gateway callout. Backend ports this via StaffHomeBase;
  // until then the live path falls back to the planner's primary district name.
  const homeDistrict = user.district ?? "—";

  // Cost engine rates (canonical, CD-set) — passed to the gateway so the
  // breakdown matches what the budget approval engine will see later.
  const visitCostRates = loadVisitCostRates();

  // Resolve active cost rates from the country cost settings — the client
  // computes activity totals from these without re-reading the server module.
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
      <PageHeader
        title="Create / Edit Plan"
        dateLabel="May 2025"
        subtitle="Pre-loaded with the highest-priority work — by SSA, training history, partner capacity, and coverage targets. Plan one activity type at a time: each tab uses its own cost formula from active Country Cost Settings."
        backFallbackHref="/plans"
      />
      {/* Step 1 — District Gateway. On MOBILE it's the first content under the
          page header; on DESKTOP it renders INSIDE the builder as the `gateway` slot. */}
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
