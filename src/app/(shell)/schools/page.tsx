import { SchoolsHeader } from "@/components/schools/SchoolsHeader";
import { DirectoryKpiStrip } from "@/components/schools/DirectoryKpiStrip";
import { PlanningReviewSignals } from "@/components/schools/PlanningReviewSignals";
import { SchoolQuickActions } from "@/components/schools/SchoolQuickActions";
import { SchoolsClusterDirectory, type DirectoryClusterOption } from "@/components/cluster/SchoolsClusterDirectory";
import type { DirectorySchoolVM, DirectoryClusterMatch } from "@/components/cluster/DirectoryClusterDrawer";
import { schoolRecommendationSummary, recommendInterventionsForSchool } from "@/lib/planning/intervention-recommendation";
import { TargetsByTimePeriodCard } from "@/components/portfolio/TargetsByTimePeriodCard";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { MobileSchoolsLive } from "@/components/mobile/views/MobileSchoolsLive";
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
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { fetchAllSchoolsForDirectory, fetchClusters, fetchAnalyticsDashboard, type BeSchoolRow, type BeCluster, type BeDashboard } from "@/lib/api/surfaces";
import { LiveBadge, BackendOfflineBanner } from "@/components/ui/BackendStatus";
import type { DirectoryMetric } from "@/lib/school-directory/directory";
import { portfolioForStaffId } from "@/lib/portfolio/portfolio";
import { activePartnerAssignmentsForSchool, schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { getVisibleProjects, projectsForSchool } from "@/lib/special-projects-mock";
import { evaluateEligibility } from "@/lib/projects/project-eligibility";
import { SSA_INTERVENTION_AREAS, deriveQuarterFromDate } from "@/lib/intake/intake-core";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { applyGeographyScope, selectionFromSearchParams, geoParamsFromSelection } from "@/lib/filters/apply-filters";
import { activeFinancialYear } from "@/lib/fy-engine";
import { engineNowIso } from "@/lib/clock";
import { isMockAllowed } from "@/lib/mock-policy";

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
// assignments yet). When the backend is off/unreachable and mock policy is off,
// the page renders honest zeros and the directory's empty state.
// TRUE portfolio aggregates from the backend's server-side counts (full 700-row
// universe, role-scoped) — NOT derived from the page-capped (<=200) row list.
// This is the correct source for the unfiltered "at a glance" strip; counting a
// truncated row page gave every breakdown the wrong value (audit P0).
function aggregateDirectoryMetrics(d: BeDashboard): DirectoryMetric[] {
  const total = d.schools;
  const denom = Math.max(total, 1);
  const pct = (n: number) => `${Math.round((n / denom) * 1000) / 10}%`;
  const clustered = total - d.unclustered;
  const ssaMiss = total - d.ssaDone;
  return [
    { key: "total", label: "Total Schools", value: total },
    { key: "client", label: "Client", value: d.clientSchools, caption: pct(d.clientSchools) },
    { key: "core", label: "Core", value: d.coreSchools, caption: pct(d.coreSchools) },
    { key: "clustered", label: "Clustered", value: clustered, caption: pct(clustered), tone: clustered ? "good" : "default" },
    { key: "unclustered", label: "Unclustered", value: d.unclustered, caption: pct(d.unclustered), tone: d.unclustered ? "alert" : "default" },
    { key: "ssa_done", label: "SSA Complete", value: d.ssaDone, caption: pct(d.ssaDone), tone: d.ssaDone ? "good" : "default" },
    { key: "ssa_miss", label: "SSA Pending", value: ssaMiss, caption: pct(ssaMiss), tone: ssaMiss ? "alert" : "default" },
  ];
}

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
export default async function SchoolsDashboard({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const me = await getCurrentUser();
  const currentUser = toCurrentUser(me);

  // Header filters → data. The HeaderFilterBar writes the selection to the
  // URL; this page reads it back and scopes everything derived from the
  // directory (KPI strip, signals, the directory rows themselves) so the
  // filters control the data, not just the chips. Role scope stays first
  // (directoryRecords); geography narrows within it.
  const selection = selectionFromSearchParams(await searchParams);

  // Canonical directory: the viewer's uploaded schools (scoped to their chain).
  const records = applyGeographyScope(
    directoryRecords(currentUser.staffId, currentUser.role),
    selection,
    // Region derives from district via the geography source of truth, so
    // the match is always consistent with the filter options.
    { district: (s) => s.district },
  );
  const mockMetrics = directoryMetrics(records);
  const signals = directoryPlanningSignals(records);

  // Portfolio strip is live from edify-api when the backend is enabled; otherwise
  // it falls back to the in-memory directory metrics (identical shape). The
  // geography filter is threaded to BOTH the row list and the aggregate so the
  // backend narrows server-side — the list is the full narrowed universe (not the
  // first 200 rows of the unfiltered set) and the strip counts that same universe.
  const geo = geoParamsFromSelection(selection);
  const liveSchools = await fetchAllSchoolsForDirectory(me, geo);
  const liveRows = liveSchools.live ? liveSchools.data : [];
  // Strip source of truth: the backend's server-side AGGREGATE counts, computed
  // over the SAME (role-scoped + geo-narrowed) universe as the row list — never
  // the <=200-row page (counting the page made every breakdown wrong, and any
  // district whose schools fell past row 200 was silently under-counted).
  const liveDashboard = await fetchAnalyticsDashboard(me, geo);
  const mockOk = isMockAllowed();
  const emptyMetrics = liveDirectoryMetrics([], 0);
  const metrics = liveSchools.live
    ? liveDashboard.live
      ? aggregateDirectoryMetrics(liveDashboard.data)
      : liveDirectoryMetrics(liveRows, liveSchools.total)
    : mockOk
      ? mockMetrics
      : emptyMetrics;
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

  // Assignment option lists for the directory drawer + bulk bar.
  const visibleProjects = getVisibleProjects(currentUser);
  const projectOptions = visibleProjects.map((p) => ({ projectId: p.projectId, projectShortName: p.projectShortName, projectType: p.projectType, primaryInterventionId: p.primaryInterventionId }));
  const interventionAreas = [...SSA_INTERVENTION_AREAS];
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

  // ── Directory rows + cluster options ──
  // BACKEND-DRIVEN when the API is live: the directory list, cluster options, and
  // per-school cluster eligibility (matches) ALL come from edify-api, so what you
  // see and assign is real backend data. Sub-county eligibility mirrors the
  // server's rule (a cluster is "strong" iff it covers the school's sub-county).
  // Falls back to the in-memory directory only when the backend is off.
  const liveClusterRes = liveSchools.live ? await fetchClusters(me) : null;
  const beClusters: BeCluster[] = liveClusterRes?.live ? liveClusterRes.data : [];
  const beClustersBySub = new Map<string, BeCluster[]>();
  for (const c of beClusters) for (const scId of c.subCountyIds ?? []) {
    const arr = beClustersBySub.get(scId) ?? [];
    arr.push(c);
    beClustersBySub.set(scId, arr);
  }
  const beMatch = (c: BeCluster, tier: "strong" | "district" | "region"): DirectoryClusterMatch => ({
    id: c.id, name: c.name, district: c.district?.name ?? "",
    subCounties: c.subCounties ?? [],
    schoolCount: c.schoolCount ?? c._count?.schools ?? 0,
    ssaRate: c.schoolCount ? Math.round(((c.schoolsWithSsa ?? 0) / c.schoolCount) * 100) : 0,
    tier, leaderName: c.clusterLeaderName ?? undefined,
  });
  const beDirectoryVM = (r: BeSchoolRow): DirectorySchoolVM => {
    const strong = r.subCountyId ? beClustersBySub.get(r.subCountyId) ?? [] : [];
    const strongIds = new Set(strong.map((c) => c.id));
    const district = beClusters.filter((c) => c.district?.name && c.district.name === r.district?.name && !strongIds.has(c.id));
    const clustered = r.clusterStatus === "clustered";
    const ssaDone = r.currentFySsaStatus === "done";
    const stage = r.accountOwnerStatus !== "matched" ? "needs_owner" as const : !clustered ? "unclustered" as const : !ssaDone ? "ssa_required" as const : "planning_ready" as const;
    return {
      schoolId: r.schoolId, schoolName: r.name,
      schoolType: r.schoolType === "core" ? "Core" : "Client",
      region: r.region?.name ?? "", district: r.district?.name ?? "",
      subCounty: r.subCounty?.name ?? undefined, parish: r.parish?.name ?? undefined,
      assignedCceo: r.accountOwner?.user?.name ?? r.accountOwnerNameRaw ?? undefined,
      ssaStatus: ssaDone ? "SSA Done" : "SSA Not Done",
      duplicate: r.duplicateStatus === "potential",
      clusterStatus: clustered ? "clustered" : "unclustered",
      clusterId: r.clusterId ?? undefined, clusterName: r.cluster?.name ?? undefined,
      stage,
      matches: { strong: strong.map((c) => beMatch(c, "strong")), district: district.map((c) => beMatch(c, "district")), region: [] },
      projects: [], recommendedProjectIds: [], delegations: [], recommendation: undefined,
    };
  };

  const clusterOptions: DirectoryClusterOption[] = liveSchools.live
    ? beClusters.map((c) => ({ id: c.id, name: c.name, district: c.district?.name ?? "" }))
    : mockOk
      ? activeClusters().map((c) => ({ id: c.id, name: c.name, district: c.district }))
      : [];

  const directorySchools: DirectorySchoolVM[] = liveSchools.live
    ? liveRows.map(beDirectoryVM)
    : mockOk
      ? records.map((s) => {
        const g = recommendClustersFor(s);
        const rec = recommendInterventionsForSchool(s.schoolId);
        const weakAreas = rec.hasSsa
          ? rec.all.slice(0, 2).map((r) => ({ area: r.intervention, score: r.score }))
          : undefined;
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
          phone: s.phone,
          primaryContact: s.primaryContact,
          weakAreas,
        };
      })
      : [];
  // The portfolio targets card + planning-review signals derive from in-memory
  // mock (portfolioForStaffId, directoryPlanningSignals over the mock directory),
  // not the live backend. The KPI strip + directory rows above ARE live — gate
  // only these two mock-fed surfaces so production shows neither fabricated.
  // Partner/HR cannot assign; everyone else with directory access can (server re-checks).
  const canManageDirectory = ["CCEO", "CountryProgramLead", "ImpactAssessment", "Admin"]
    .includes(currentUser.role);
  // Cluster assignment is a CCEO/PL responsibility — the Project Coordinator
  // (whose appRole projects to CountryProgramLead) only views clusters.
  const canManageClusters = canManageDirectory && me.role !== "ProjectCoordinator";

  return (
    <ResponsiveDashboard mobile={<MobileSchoolsLive schools={directorySchools} live={liveSchools.live} />} desktop={
    <>
      <SchoolsHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* Portfolio at a glance — dense metric strip (role-scoped).
              Replaces the 9-tile KPI grid + the redundant donut snapshot:
              one scannable band, proportions carried as captions.
              Values are live from edify-api when the backend is enabled. */}
          {metricsLive && <LiveBadge />}
          <BackendOfflineBanner error={metricsError} />
          <DirectoryKpiStrip metrics={metrics} title="Portfolio at a glance" />

          {/* Portfolio targets — cumulative FY progress (shown when you own schools).
              Mock-derived; withheld in production. */}
          {mockOk && portfolio.schools.length > 0 && (
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
            userRole={currentUser.role}
            userName={currentUser.name}
            clusterOptions={clusterOptions}
            projectOptions={projectOptions}
            partnerOptions={PARTNER_SUGGESTIONS}
            interventionAreas={interventionAreas}
          />

          {/* Planning-readiness signals — the actionable workflow stages
              (counts duplicated by the strip above were removed). Mock-derived;
              withheld in production. */}
          {mockOk && <PlanningReviewSignals signals={signals} />}

          {/* Quick actions — permission-aware */}
          <SchoolQuickActions user={currentUser} />
        </div>
      </>
    } />
  );
}
