import { SchoolsHeader } from "@/components/schools/SchoolsHeader";
import { MetricStrip } from "@/components/ui/MetricStrip";
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
  directoryMetrics,
  directoryPlanningSignals,
} from "@/lib/school-directory/directory";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import { getVisibleSchools, priorityOrder } from "@/lib/schools-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { fetchSchools, type BeSchoolRow } from "@/lib/api/surfaces";
import { LiveBadge, BackendOfflineBanner } from "@/components/ui/BackendStatus";
import type { DirectoryMetric } from "@/lib/school-directory/directory";
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

// Portfolio "at a glance" cells computed from the live backend school list
// (scoped server-side by the caller's role). Mirrors directoryMetrics, minus the
// partner-supported cell (the backend directory feed doesn't carry partner
// assignments yet). When the backend is off/unreachable the page uses the
// in-memory directoryMetrics instead — same shape, so the strip is identical.
function liveDirectoryMetrics(rows: BeSchoolRow[], total: number): DirectoryMetric[] {
  const denom = Math.max(total, 1);
  const pct = (n: number) => `${Math.round((n / denom) * 1000) / 10}%`;
  const count = (pred: (r: BeSchoolRow) => boolean) => rows.filter(pred).length;
  const core = count((r) => r.schoolType === "core");
  const client = count((r) => r.schoolType === "client");
  const clustered = count((r) => r.clusterStatus === "clustered");
  const unclustered = total - clustered;
  const ssaDone = count((r) => r.currentFySsaStatus === "done");
  const ssaMiss = total - ssaDone;
  const owned = count((r) => r.accountOwnerStatus === "matched");
  return [
    { key: "total", label: "Total Schools", value: total },
    { key: "client", label: "Client", value: client, caption: pct(client) },
    { key: "core", label: "Core", value: core, caption: pct(core) },
    { key: "clustered", label: "Clustered", value: clustered, caption: pct(clustered), tone: clustered ? "good" : "default" },
    { key: "unclustered", label: "Unclustered", value: unclustered, caption: pct(unclustered), tone: unclustered ? "alert" : "default" },
    { key: "ssa_done", label: "SSA Complete", value: ssaDone, caption: pct(ssaDone), tone: ssaDone ? "good" : "default" },
    { key: "ssa_miss", label: "SSA Pending", value: ssaMiss, caption: pct(ssaMiss), tone: ssaMiss ? "alert" : "default" },
    { key: "staff", label: "Owned by Staff", value: owned, caption: pct(owned) },
  ];
}

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
  const mockMetrics = directoryMetrics(records);
  const signals = directoryPlanningSignals(records);

  // Portfolio strip is live from edify-api when the backend is enabled; otherwise
  // it falls back to the in-memory directory metrics (identical shape).
  const liveSchools = await fetchSchools(me, { pageSize: 200 });
  const metrics = liveSchools.live
    ? liveDirectoryMetrics(liveSchools.data.data, liveSchools.data.total)
    : mockMetrics;
  const metricsLive = liveSchools.live;
  const metricsError = liveSchools.live ? null : liveSchools.error;

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
          {/* Portfolio at a glance — dense metric strip (role-scoped).
              Replaces the 9-tile KPI grid + the redundant donut snapshot:
              one scannable band, proportions carried as captions.
              Values are live from edify-api when the backend is enabled. */}
          {metricsLive && <LiveBadge />}
          <BackendOfflineBanner error={metricsError} />
          <MetricStrip
            title="Portfolio at a glance"
            metrics={metrics}
            columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8"
          />

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

          {/* Planning-readiness signals — the actionable workflow stages
              (counts duplicated by the strip above were removed). */}
          <PlanningReviewSignals signals={signals} />

          {/* Quick actions — permission-aware */}
          <SchoolQuickActions user={currentUser} />
        </div>
      </>
    } />
  );
}
