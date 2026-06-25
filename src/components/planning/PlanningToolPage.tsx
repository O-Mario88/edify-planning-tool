import { PlanningTopHeader } from "./PlanningTopHeader";
import { OperationalCycleBanner } from "./OperationalCycleBanner";
import { UnclusteredSchoolsBanner } from "./UnclusteredSchoolsBanner";
import { PlanningGapBoard } from "./PlanningGapBoard";
import { PlanningOwnershipSections } from "./PlanningOwnershipSections";
import { PlansFamilyNav } from "./PlansFamilyNav";
import { PlanningCategorySummary } from "./PlanningCategorySummary";
import { ProjectPlanningGaps } from "@/components/special-projects/ProjectPlanningGaps";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { onboardedSchoolGaps, scopeGapsToViewer } from "@/lib/planning/onboarded-gaps";
import { fetchBackendSchoolGaps } from "@/lib/planning/backend-school-gaps";
import { backendCoreSchoolGaps } from "@/lib/planning/backend-core-school-gaps";
import { fetchBackendClusterGaps } from "@/lib/planning/backend-cluster-gaps";
import { isBackendEnabled } from "@/lib/api/backend";
import { isMockAllowed } from "@/lib/mock-policy";
import { assignedGapIds } from "@/lib/planning/assignment-overlay";
import { coreOwnershipRows, resolveCoreBoardData } from "@/lib/core/core-board";
import { engineClusterGaps } from "@/lib/planning/engine-cluster-gaps";
import { directoryRecords } from "@/lib/school-directory/directory";
import { computeProjectPlanningGaps } from "@/lib/projects/project-planning-gaps";
import { buildPlanningCategories } from "@/lib/planning/planning-categories";
import { loadVisitCostRates, loadGroupActivityRates } from "@/lib/cost-engine/cost-engine-server";
import { applyGeographyScope, selectionFromSearchParams } from "@/lib/filters/apply-filters";

// PlanningToolPage no longer renders its own sidebar — the (shell)
// route-group layout mounts <EdifySidebarServer /> once for every
// authenticated page (and resolves the menu from the signed-in user's
// role, not a hard-coded prop).
//
// The bottom "schedule visits + trainings only" banner and the
// "as of {date} · refresh" footer have been retired: the banner copy now
// lives in the header's HelpCircle tooltip, and the refresh signal lives
// in the header's "Snapshot · <timestamp>" badge.
export async function PlanningToolPage({
  topSlot,
  searchParams = {},
}: {
  topSlot?: React.ReactNode;
  searchParams?: Record<string, string | string[] | undefined>;
} = {}) {
  // Onboarded schools (+ their uploaded SSA) become planner gaps, scoped to the
  // viewer's supervision chain. Computed server-side so runtime uploads show.
  const user = await getCurrentUser();
  // Header filters → data. Geography scope only (district + region derived from
  // district via the geography source of truth). Gap rows carry no FY/quarter
  // planning date (a gap is by definition unscheduled) and no cluster id in the
  // filter's clusterOptions id space (clustersMock CLT-*), so those dimensions
  // stay off here rather than faking matches.
  const selection = selectionFromSearchParams(searchParams);
  // Prefer REAL backend gaps; fall back to mock onboarded gaps only in dev/mock mode.
  const schoolFetch = await fetchBackendSchoolGaps(user);
  const backendGaps = schoolFetch.gaps;
  const gapsLoadError = schoolFetch.error;
  const assigned = assignedGapIds();
  const mockGaps = scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role)
    .filter((g) => !assigned.has(g.id));
  const onboardedGaps =
    backendGaps !== null
      ? backendGaps
      : isMockAllowed()
        ? applyGeographyScope(mockGaps, selection, { district: (g) => g.district })
        : [];
  const liveGaps = backendGaps !== null;
  // Cluster-first: count the viewer's unclustered schools so the Planning Tool
  // leads with the cluster-assignment call to action when any are outstanding.
  // Counted AFTER geo scoping so the banner obeys the header filters.
  const unclusteredCount = onboardedGaps.filter((g) => g.gapCategory === "no_cluster").length;
  // Cluster gaps: prefer the REAL backend (clusters + slot status derived from
  // real activities); fall back to the mock engine when the backend is off.
  // ClusterGap ids live in the cluster-engine/backend id space (CLU-*/cuid),
  // not the filter's clusterOptions space (CLT-*) — district only here.
  const clusterFetch = await fetchBackendClusterGaps(user);
  const backendClGaps = clusterFetch.gaps;
  const clusterLoadError = clusterFetch.error;
  const clusterGaps = applyGeographyScope(
    backendClGaps ?? (isMockAllowed() ? engineClusterGaps() : []),
    selection,
    { district: (c) => c.district },
  );
  const liveClusterGaps = backendClGaps !== null;

  // Project follow-up gaps, scoped like the directory: CCEO/PL see their
  // portfolio/team schools; broader roles see all in-scope project schools.
  const scoped: Set<string> | "all" =
    user.role === "CCEO" || user.role === "CountryProgramLead"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";
  // ProjectGapItem carries district only (no cluster id, no date) — scope each
  // category's items so the section counts obey the header filters too.
  const projectGaps = computeProjectPlanningGaps(toCurrentUser(user), scoped).map((cat) => ({
    ...cat,
    items: applyGeographyScope(cat.items, selection, { district: (i) => i.district }),
  }));

  // Core Schools tab — backend plans when the bridge is live.
  const coreCardsRaw = await resolveCoreBoardData(
    { email: user.email, role: user.role },
    user.staffId,
    user.role,
  );
  const coreCards = applyGeographyScope(coreCardsRaw, selection, {
    district: (c) => c.district,
  });
  // Backend core-school gaps — when live, the Core Schools tab renders the SAME
  // detail-rich gap rows as Client Schools (schedule/assign → My Plan).
  const backendCoreGaps = await backendCoreSchoolGaps(user);
  const liveCoreGaps = backendCoreGaps !== null;
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "Admin"].includes(user.role);
  // CoreOwnershipRow carries no geography (schoolId/slot only) — left unscoped.
  const coreOwnership = coreOwnershipRows(user.staffId, user.role);

  // CCEO-only recommendation-led summary (spec §9): the SAME scoped gap data
  // the boards below consume, folded into 8 expandable categories. Built here
  // (not recomputed in the engine) so every row stays viewer- + filter-scoped
  // and, by construction, unscheduled.
  const planningCategories =
    user.role === "CCEO"
      ? buildPlanningCategories({
          schoolGaps: onboardedGaps,
          clusterGaps,
          coreCards,
          projectGaps,
          rates: { visit: loadVisitCostRates(), group: loadGroupActivityRates() },
        })
      : null;

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
            (Awaiting Partner Schedule + Planned This Month moved to /my-plan —
             they track already-planned work, not gaps.)
            (PlanningGapsHero retired per global hero removal pass.) */}
        <OperationalCycleBanner />

        {isBackendEnabled() && (gapsLoadError || clusterLoadError) && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 font-semibold">
            Could not load planning data from the backend
            {(gapsLoadError ?? clusterLoadError) ? ` (${gapsLoadError ?? clusterLoadError})` : ""}.
          </div>
        )}

        {/* Tabs sit DIRECTLY under the operational-cycle card — the single
            switcher (Client Schools · Clusters · Core Schools) that separates
            the three planning surfaces. Each tab is the detail-rich, backend-
            driven gap board; the old standalone "schools-by-stage" and
            "cluster planning" cards are merged into these tabs. */}
        <UnclusteredSchoolsBanner count={unclusteredCount} />

        <PlanningGapBoard assigningUserRole={user.role} extraGaps={onboardedGaps} liveGaps={liveGaps} clusterGaps={clusterGaps} liveClusterGaps={liveClusterGaps} coreCards={coreCards} coreGaps={backendCoreGaps ?? []} liveCoreGaps={liveCoreGaps} coreViewer={coreViewer} canChampion={canChampion} />

        {/* Secondary context below the boards. */}
        {topSlot}

        {planningCategories && <PlanningCategorySummary categories={planningCategories} />}

        <PlansFamilyNav current="planning" className="flex items-center gap-1" />

        <PlanningOwnershipSections ownership={coreOwnership} show={["assignedToMe", "assignedToPartner"]} />

        <ProjectPlanningGaps categories={projectGaps} />
      </div>
    </>
  );
}
