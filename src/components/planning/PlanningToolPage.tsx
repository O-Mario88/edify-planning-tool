import { PlanningTopHeader } from "./PlanningTopHeader";
import { OperationalCycleBanner } from "./OperationalCycleBanner";
import { SchoolGapsBoard } from "./SchoolGapsBoard";
import { ClusterGapsBoard } from "./ClusterGapsBoard";
import { CoreSchoolsGapPlanning } from "./CoreSchoolsGapPlanning";
import { PlanningOwnershipSections } from "./PlanningOwnershipSections";
import { PlansFamilyNav } from "./PlansFamilyNav";

// PlanningToolPage no longer renders its own sidebar — the (shell)
// route-group layout mounts <EdifySidebarServer /> once for every
// authenticated page (and resolves the menu from the signed-in user's
// role, not a hard-coded prop).
//
// The bottom "schedule visits + trainings only" banner and the
// "as of {date} · refresh" footer have been retired: the banner copy now
// lives in the header's HelpCircle tooltip, and the refresh signal lives
// in the header's "Snapshot · <timestamp>" badge.
export function PlanningToolPage() {
  return (
    <>
      <PlanningTopHeader />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {/* ───── Planning page flow ─────
            0. Operational cycle banner ← cycle context, sits directly
               under the header so the CCEO/PL sees which cycle they're
               planning into BEFORE looking at the gap counts below.
            1. Client school gap card
            2. Cluster gap card
            3. Core Schools Gap Planning  ← SSA-driven section
            4. Assigned to Me
            5. Assigned to Partner
            6. Awaiting Partner Schedule
            7. Planned This Month
            (PlanningGapsHero retired per global hero removal pass.) */}
        <OperationalCycleBanner />

        <PlansFamilyNav current="planning" className="flex items-center gap-1" />
        <SchoolGapsBoard />
        <ClusterGapsBoard />
        <CoreSchoolsGapPlanning />

        <PlanningOwnershipSections />
      </div>
    </>
  );
}
