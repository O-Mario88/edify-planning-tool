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
import { backendSchoolGaps } from "@/lib/planning/backend-school-gaps";
import { backendCoreSchoolGaps } from "@/lib/planning/backend-core-school-gaps";
import { backendClusterGaps } from "@/lib/planning/backend-cluster-gaps";
import { assignedGapIds } from "@/lib/planning/assignment-overlay";
import { coreBoardData, coreOwnershipRows } from "@/lib/core/core-board";
import { engineClusterGaps } from "@/lib/planning/engine-cluster-gaps";
import { directoryRecords } from "@/lib/school-directory/directory";
import { computeProjectPlanningGaps } from "@/lib/projects/project-planning-gaps";
import { buildPlanningCategories } from "@/lib/planning/planning-categories";
import { loadVisitCostRates, loadGroupActivityRates } from "@/lib/cost-engine/cost-engine-server";
import { applyGeographyScope, selectionFromSearchParams } from "@/lib/filters/apply-filters";
import { isMockAllowed } from "@/lib/mock-policy";

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
  // Prefer REAL backend gaps (live schools, live scheduling); fall back to the
  // mock onboarded gaps only when the backend is disabled.
  const backendGaps = await backendSchoolGaps(user);
  const assigned = assignedGapIds();
  const mockGaps = scopeGapsToViewer(onboardedSchoolGaps(), user.staffId, user.role)
    .filter((g) => !assigned.has(g.id));
  // Backend gap rows carry no district yet (BePlanningSchool has no geography),
  // so geography scope applies on the mock path only — scoping live rows by a
  // field they lack would empty the board, not filter it.
  const onboardedGaps =
    backendGaps ?? applyGeographyScope(mockGaps, selection, { district: (g) => g.district });
  const liveGaps = backendGaps !== null;
  // Cluster-first: count the viewer's unclustered schools so the Planning Tool
  // leads with the cluster-assignment call to action when any are outstanding.
  // Counted AFTER geo scoping so the banner obeys the header filters.
  const unclusteredCount = onboardedGaps.filter((g) => g.gapCategory === "no_cluster").length;
  // Cluster gaps: prefer the REAL backend (clusters + slot status derived from
  // real activities); fall back to the mock engine when the backend is off.
  // ClusterGap ids live in the cluster-engine/backend id space (CLU-*/cuid),
  // not the filter's clusterOptions space (CLT-*) — district only here.
  const backendClGaps = await backendClusterGaps(user);
  const clusterGaps = applyGeographyScope(backendClGaps ?? engineClusterGaps(), selection, {
    district: (c) => c.district,
  });
  const liveClusterGaps = backendClGaps !== null;

  // Mock policy gate: in production (and this backend-on stack) frontend mock
  // fixtures must never render. The school + cluster gap boards above are already
  // backend-driven; the remaining mock-only surfaces (project follow-up gaps, the
  // CorePlan board, ownership rows) are gated on this flag so they resolve to
  // empty instead of leaking fabricated schools (e.g. "Nakaseke Hill Primary").
  const mockOk = isMockAllowed();

  // Project follow-up gaps, scoped like the directory: CCEO/PL see their
  // portfolio/team schools; broader roles see all in-scope project schools.
  // These derive from the special-projects mock (no backend project-gaps
  // endpoint yet), so they only render when mock is allowed.
  const scoped: Set<string> | "all" =
    user.role === "CCEO" || user.role === "CountryProgramLead"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";
  // ProjectGapItem carries district only (no cluster id, no date) — scope each
  // category's items so the section counts obey the header filters too.
  const projectGaps = mockOk
    ? computeProjectPlanningGaps(toCurrentUser(user), scoped).map((cat) => ({
        ...cat,
        items: applyGeographyScope(cat.items, selection, { district: (i) => i.district }),
      }))
    : [];

  // Backend core-school gaps — when live, the Core Schools tab renders the SAME
  // detail-rich gap rows as Client Schools (schedule/assign → My Plan).
  const backendCoreGaps = await backendCoreSchoolGaps(user);
  const liveCoreGaps = backendCoreGaps !== null;
  // The mock CorePlan board + ownership rows are dev-only fixtures. When the
  // backend core gaps are live the Core Schools tab uses THEM (not coreCards),
  // so mock coreCards/coreOwnership must never leak into a live board, the CCEO
  // category summary, or the ownership sections — gate both on mockOk above.
  // CorePlanCardVM.cluster is a display NAME, not a filter cluster id — district only.
  const coreCards = mockOk
    ? applyGeographyScope(coreBoardData(user.staffId, user.role), selection, { district: (c) => c.district })
    : [];
  const coreViewer = {
    canAssign: ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"].includes(user.role),
    canExec: ["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"].includes(user.role),
    canIa: ["ImpactAssessment", "Admin"].includes(user.role),
  };
  const canChampion = ["ImpactAssessment", "CountryProgramLead", "CountryDirector", "Admin"].includes(user.role);
  // CoreOwnershipRow carries no geography (schoolId/slot only) — left unscoped.
  // Mock-gated: the ownership rows are fixtures with no backend endpoint yet, so
  // outside dev the sections render their controlled empty state instead of
  // fabricated "assigned to me / partner" rows.
  const coreOwnership = mockOk ? coreOwnershipRows(user.staffId, user.role) : undefined;

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
            4. Awaiting Partner Schedule
            5. Planned This Month
            (PlanningGapsHero retired per global hero removal pass.) */}
        <OperationalCycleBanner />

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

        <PlanningOwnershipSections ownership={coreOwnership} />

        <ProjectPlanningGaps categories={projectGaps} />
      </div>
    </>
  );
}
