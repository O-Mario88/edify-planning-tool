import { PlanningToolPage } from "@/components/planning/PlanningToolPage";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PlanningMobileView } from "@/components/mobile/views/PlanningMobileView";
import { PlanningGapBoard } from "@/components/planning/PlanningGapBoard";

// The OperationalCycleBanner now renders inside PlanningToolPage,
// below PlanningTopHeader, so the cycle context sits where the rest
// of the planning chrome does instead of floating above it.
// PlansFamilyNav also moved inside PlanningToolPage — it now sits
// directly above the Client School Gap card instead of floating
// above the page header.
//
// PlanningGapBoard is the new SSA-gated, gap-based Planning view. It
// renders above the existing PlanningToolPage during the transition —
// the legacy components stay in place until the gap engine reaches
// parity with their flows, at which point we'll retire them in a
// follow-up phase.
export default function Page() {
  return (
    <>
      <div className="px-4 md:px-6 lg:px-8 pt-4">
        <PlanningGapBoard />
      </div>
      <ResponsiveDashboard
        desktop={<PlanningToolPage />}
        mobile={<PlanningMobileView />}
      />
    </>
  );
}
