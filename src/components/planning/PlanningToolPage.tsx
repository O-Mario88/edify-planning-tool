import { PlanningTopHeader } from "./PlanningTopHeader";
import { OperationalCycleBanner } from "./OperationalCycleBanner";
import { UnclusteredSchoolsBanner } from "./UnclusteredSchoolsBanner";
import { PlanningGapBoard } from "./PlanningGapBoard";
import { PlanningOwnershipSections } from "./PlanningOwnershipSections";
import { PlansFamilyNav } from "./PlansFamilyNav";
import { getCurrentUser } from "@/lib/auth";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";

// PlanningToolPage no longer renders its own sidebar — the (shell)
// route-group layout mounts <EdifySidebarServer /> once for every
// authenticated page (and resolves the menu from the signed-in user's
// role, not a hard-coded prop).
//
// The bottom "schedule visits + trainings only" banner and the
// "as of {date} · refresh" footer have been retired: the banner copy now
// lives in the header's HelpCircle tooltip, and the refresh signal lives
// in the header's "Snapshot · <timestamp>" badge.
export async function PlanningToolPage() {
  // Onboarded schools (+ their uploaded SSA) become planner gaps, scoped to the
  // viewer's supervision chain. Computed server-side so runtime uploads show.
  const user = await getCurrentUser();
  const onboardedGaps = scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role);
  // Cluster-first: count the viewer's unclustered schools so the Planning Tool
  // leads with the cluster-assignment call to action when any are outstanding.
  const unclusteredCount = onboardedGaps.filter((g) => g.gapCategory === "no_cluster").length;

  return (
    <>
      <PlanningTopHeader />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        {/* ───── Planning page flow ─────
            0. Operational cycle banner ← cycle context, sits directly
               under the header so the CCEO/PL sees which cycle they're
               planning into BEFORE looking at the gap counts below.
            1. Gap board ← one tabbed switcher (Client Schools · Clusters ·
               Core Schools), each a neat collapsible, detail-rich board.
            2. Assigned to Me
            3. Assigned to Partner
            4. Awaiting Partner Schedule
            5. Planned This Month
            (PlanningGapsHero retired per global hero removal pass.) */}
        <OperationalCycleBanner />

        <UnclusteredSchoolsBanner count={unclusteredCount} />

        <PlansFamilyNav current="planning" className="flex items-center gap-1" />
        <PlanningGapBoard extraGaps={onboardedGaps} />

        <PlanningOwnershipSections />
      </div>
    </>
  );
}
