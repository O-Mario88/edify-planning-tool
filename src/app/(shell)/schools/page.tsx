import { SchoolsHeader } from "@/components/schools/SchoolsHeader";
import { SchoolKpiRow } from "@/components/schools/SchoolKpiRow";
import { SchoolStatusSnapshot } from "@/components/schools/SchoolStatusSnapshot";
import { PlanningReviewSignals } from "@/components/schools/PlanningReviewSignals";
import { SchoolQuickActions } from "@/components/schools/SchoolQuickActions";
import { SchoolsClusterDirectory, type DirectoryClusterOption } from "@/components/cluster/SchoolsClusterDirectory";
import type { DirectorySchoolVM, DirectoryClusterMatch } from "@/components/cluster/DirectoryClusterDrawer";
import { schoolRecommendationSummary } from "@/lib/planning/intervention-recommendation";
import { TargetsByTimePeriodCard } from "@/components/portfolio/TargetsByTimePeriodCard";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SchoolsView } from "@/components/mobile/views/SchoolsView";
import {
  clusterStatusOf,
  recommendClustersFor,
  activeClusters,
  type ClusterMatch,
} from "@/lib/cluster/cluster-core";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import {
  directoryRecords,
  directoryKpis,
  directoryStatusSnapshot,
  directoryPlanningSignals,
} from "@/lib/school-directory/directory";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import { getVisibleSchools, priorityOrder } from "@/lib/schools-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { activePartnerAssignmentsForSchool, schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { getVisibleProjects, projectsForSchool } from "@/lib/special-projects-mock";
import { evaluateEligibility } from "@/lib/projects/project-eligibility";
import { SSA_INTERVENTION_AREAS, deriveQuarterFromDate } from "@/lib/intake/intake-core";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { activeFinancialYear } from "@/lib/fy-engine";
import { engineNowIso } from "@/lib/clock";

const PARTNER_SUGGESTIONS = [
  "Hope Education Partners",
  "Bright Future Education Partners",
  "Literacy Training Uganda",
  "Numeracy First",
  "Northern Education Trust",
  "Mastercard Foundation",
];

// School Directory = Portfolio = source of truth. KPIs, snapshot, signals, the
// directory itself, AND every assignment (cluster, special project, partner) all
// run off the uploaded schools (intakeSchools) via the canonical accessor — one
// page, one universe. The old separate /portfolio + /clusters/assign surfaces
// fold in here. (The mobile view still renders the legacy SchoolRow set.)
export default async function SchoolsDashboard() {
  const me = await getCurrentUser();
  const currentUser = toCurrentUser(me);

  // Canonical directory: the viewer's uploaded schools (scoped to their chain).
  const records = directoryRecords(currentUser.staffId, currentUser.role);
  const kpis = directoryKpis(records);
  const snapshot = directoryStatusSnapshot(records);
  const signals = directoryPlanningSignals(records);

  // Portfolio targets — only when the viewer personally OWNS schools (CCEO/PL).
  // Cumulative against the portfolio (Q1 25% · Q2 50% · Q3 75% · Q4 100%).
  const portfolio = portfolioForStaffId(currentUser.staffId);
  const fy = activeFinancialYear();
  const withPartnerSet = schoolIdsWithActivePartner();
  const supported = portfolio.schools.filter(
    (s) => s.ssaStatus === "SSA Done" || withPartnerSet.has(s.schoolId),
  ).length;
  const currentQuarter = deriveQuarterFromDate(engineNowIso());
  const periodTarget = computePeriodTarget({
    fyTarget: portfolio.counts.total,
    achieved: supported,
    selectedQuarter: currentQuarter,
  });

  // Mobile view still uses the legacy SchoolRow set (separate migration).
  const ordered = [...getVisibleSchools(currentUser)].sort(priorityOrder);

  // Assignment option lists for the directory drawer + bulk bar.
  const clusterOptions: DirectoryClusterOption[] = activeClusters().map((c) => ({ id: c.id, name: c.name, district: c.district }));
  const visibleProjects = getVisibleProjects(currentUser);
  const projectOptions = visibleProjects.map((p) => ({ projectId: p.projectId, projectShortName: p.projectShortName, projectType: p.projectType, primaryInterventionId: p.primaryInterventionId }));
  const interventionAreas = [...SSA_INTERVENTION_AREAS];

  // ── Directory rows (same master, enriched with workflow state + memberships). ──
  const dupeIds = new Set(openDuplicateCandidates().map((d) => d.schoolId));
  const toMatchVM = (m: ClusterMatch): DirectoryClusterMatch => ({
    id: m.cluster.id,
    name: m.cluster.name,
    district: m.cluster.district,
    subCounties: m.cluster.subCounties ?? [],
    schoolCount: m.schoolCount,
    ssaRate: m.ssaRate,
    tier: m.tier,
    leaderName: m.cluster.clusterLeaderName,
  });
  const directorySchools: DirectorySchoolVM[] = records.map((s) => {
    const g = recommendClustersFor(s);
    return {
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      schoolType: s.schoolType,
      region: s.region,
      district: s.district,
      subCounty: s.subCounty,
      parish: s.parish,
      assignedCceo: s.assignedCceo,
      ssaStatus: s.ssaStatus,
      duplicate: dupeIds.has(s.schoolId),
      clusterStatus: clusterStatusOf(s),
      clusterId: s.clusterId,
      clusterName: s.cluster,
      stage: schoolWorkflowState(s).stage,
      matches: { strong: g.strong.map(toMatchVM), district: g.district.map(toMatchVM), region: g.region.map(toMatchVM) },
      projects: projectsForSchool(s.schoolId),
      recommendedProjectIds: visibleProjects
        .filter((p) => evaluateEligibility(s, p).recommended)
        .map((p) => p.projectId),
      delegations: activePartnerAssignmentsForSchool(s.schoolId).map((p) => ({ id: p.id, partnerName: p.partnerName, interventionArea: p.interventionArea })),
      recommendation: schoolRecommendationSummary(s.schoolId),
    };
  });
  // Partner/HR cannot assign; everyone else with directory access can (server re-checks).
  const canManageDirectory = ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"]
    .includes(currentUser.role);
  // Cluster assignment is a CCEO/PL responsibility — the Project Coordinator
  // (whose appRole projects to CountryProgramLead) only views clusters.
  const canManageClusters = canManageDirectory && me.role !== "ProjectCoordinator";

  return (
    <ResponsiveDashboard mobile={<SchoolsView intelligenceSchools={ordered} />} desktop={
    <>
      <SchoolsHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* KPI Row — 9 cards (role-scoped) */}
          <SchoolKpiRow kpis={kpis} />

          {/* Portfolio targets — cumulative FY progress (shown when you own schools) */}
          {portfolio.schools.length > 0 && (
            <TargetsByTimePeriodCard
              fyLabel={fy.label}
              fyTarget={portfolio.counts.total}
              achieved={supported}
              partnerSupported={portfolio.counts.partnerAssigned}
              currentQuarter={currentQuarter}
              expectedCumulative={periodTarget.expectedCumulative}
              paceStatus={periodTarget.paceStatus}
            />
          )}

          {/* The directory itself — the uploaded schools (source of truth), with
              their workflow stage + every assignment launched from here. */}
          <SchoolsClusterDirectory
            schools={directorySchools}
            canManage={canManageDirectory}
            canManageClusters={canManageClusters}
            clusterOptions={clusterOptions}
            projectOptions={projectOptions}
            partnerOptions={PARTNER_SUGGESTIONS}
            interventionAreas={interventionAreas}
          />

          {/* Status snapshot + Planning signals — from the master */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 md:col-span-7">
              <SchoolStatusSnapshot tiles={snapshot} />
            </div>
            <div className="col-span-12 md:col-span-5">
              <PlanningReviewSignals signals={signals} />
            </div>
          </section>

          {/* Quick actions — permission-aware */}
          <SchoolQuickActions user={currentUser} />
        </div>
      </>
    } />
  );
}
