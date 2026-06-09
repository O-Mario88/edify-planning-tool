import { PlanningTopHeader } from "./PlanningTopHeader";
import { OperationalCycleBanner } from "./OperationalCycleBanner";
import { UnclusteredSchoolsBanner } from "./UnclusteredSchoolsBanner";
import { PlanningGapBoard } from "./PlanningGapBoard";
import { PlanningOwnershipSections } from "./PlanningOwnershipSections";
import { PlansFamilyNav } from "./PlansFamilyNav";
import { ProjectPlanningGaps } from "@/components/special-projects/ProjectPlanningGaps";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";
import { backendSchoolGaps } from "@/lib/planning/backend-school-gaps";
import { assignedGapIds } from "@/lib/planning/assignment-overlay";
import { coreBoardData, coreOwnershipRows } from "@/lib/core/core-board";
import { engineClusterGaps } from "@/lib/planning/engine-cluster-gaps";
import { directoryRecords } from "@/lib/school-directory/directory";
import { computeProjectPlanningGaps } from "@/lib/projects/project-planning-gaps";

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
  // Prefer REAL backend gaps (live schools, live scheduling); fall back to the
  // mock onboarded gaps only when the backend is disabled.
  const backendGaps = await backendSchoolGaps(user);
  const assigned = assignedGapIds();
  const mockGaps = scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role)
    .filter((g) => !assigned.has(g.id));
  const onboardedGaps = backendGaps ?? mockGaps;
  const liveGaps = backendGaps !== null;
  // Cluster-first: count the viewer's unclustered schools so the Planning Tool
  // leads with the cluster-assignment call to action when any are outstanding.
  const unclusteredCount = onboardedGaps.filter((g) => g.gapCategory === "no_cluster").length;
  // Cluster gaps now come from the real cluster engine (clusters + their
  // scheduled/completed meetings), so the planning board reflects live truth.
  const clusterGaps = engineClusterGaps();

  // Project follow-up gaps, scoped like the directory: CCEO/PL see their
  // portfolio/team schools; broader roles see all in-scope project schools.
  const scoped: Set<string> | "all" =
    user.role === "CCEO" || user.role === "CountryProgramLead"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";
  const projectGaps = computeProjectPlanningGaps(toCurrentUser(user), scoped);

  // Core Schools tab consumes the unified CorePlan model (same as the
  // dedicated /planning/core-schools console).
  const coreCards = coreBoardData(user.staffId, user.role);
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);
  const coreOwnership = coreOwnershipRows(user.staffId, user.role);

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
        <PlanningGapBoard extraGaps={onboardedGaps} liveGaps={liveGaps} clusterGaps={clusterGaps} coreCards={coreCards} coreViewer={coreViewer} canChampion={canChampion} />

        <PlanningOwnershipSections ownership={coreOwnership} />

        <ProjectPlanningGaps categories={projectGaps} />
      </div>
    </>
  );
}
