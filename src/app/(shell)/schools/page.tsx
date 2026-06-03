import { SchoolsHeader } from "@/components/schools/SchoolsHeader";
import { SchoolKpiRow } from "@/components/schools/SchoolKpiRow";
import { SchoolsIntelligence } from "@/components/schools/SchoolsIntelligence";
import { SchoolsDirectorySection } from "@/components/schools/SchoolsDirectorySection";
import { ClustersCard } from "@/components/schools/ClustersCard";
import { SchoolStatusSnapshot } from "@/components/schools/SchoolStatusSnapshot";
import { PlanningReviewSignals } from "@/components/schools/PlanningReviewSignals";
import { SchoolQuickActions } from "@/components/schools/SchoolQuickActions";
import { SchoolsClusterDirectory } from "@/components/cluster/SchoolsClusterDirectory";
import type { DirectorySchoolVM, DirectoryClusterMatch } from "@/components/cluster/DirectoryClusterDrawer";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SchoolsView } from "@/components/mobile/views/SchoolsView";
import { intakeSchools } from "@/lib/intake/intake-mock";
import {
  clusterStatusOf,
  recommendClustersFor,
  type ClusterMatch,
} from "@/lib/cluster/cluster-core";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import {
  getVisibleSchools,
  getClustersFor,
  computeKpisFor,
  computeStatusSnapshot,
  computePlanningSignals,
  countryKpiOverrides,
  countryPlanningSignalOverrides,
  priorityOrder,
  type SchoolKpi,
  type StatusSnapshotTile,
  type PlanningSignal,
} from "@/lib/schools-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";

// Server-side access control: the "all schools" array exists at the data
// layer, but only the rows owned by currentUser ever reach the page.
// In production this is a parameterized SQL query; getVisibleSchools()
// preserves that intent in mock form.
//
// Country-wide values (512 / 436 / etc.) shown in the screenshot are kept
// for visual fidelity by the override branch — they only render for
// non-CCEO roles. A CCEO sees aggregates of their own assigned set.
function applyCountryOverrideKpis(kpis: SchoolKpi[]): SchoolKpi[] {
  return kpis.map((k) => ({
    ...k,
    value: countryKpiOverrides[k.key] ?? k.value,
  }));
}

function applyCountryOverrideSnapshot(tiles: StatusSnapshotTile[]): StatusSnapshotTile[] {
  return tiles.map((t) => {
    const v = countryKpiOverrides[t.key] ?? t.value;
    const total = countryKpiOverrides.total ?? 1;
    return { ...t, value: v, pct: Math.round((v / total) * 1000) / 10 };
  });
}

function applyCountryOverrideSignals(signals: PlanningSignal[]): PlanningSignal[] {
  return signals.map((s) => ({
    ...s,
    value: countryPlanningSignalOverrides[s.key] ?? s.value,
  }));
}

export default async function SchoolsDashboard() {
  const currentUser = toCurrentUser(await getCurrentUser());
  // 1. ENFORCE access control. CCEO sees only their assigned schools.
  const visible = getVisibleSchools(currentUser);

  // 2. SSA-first priority ordering for table + urgent panel.
  const ordered = [...visible].sort(priorityOrder);
  const clusters = getClustersFor(currentUser);

  // 3. Compute aggregates from the visible set (CCEO-scoped) or country
  //    overrides (when role widens to country-level dashboards).
  const useCountry = currentUser.role !== "CCEO";

  const kpis = useCountry
    ? applyCountryOverrideKpis(computeKpisFor(visible))
    : computeKpisFor(visible);

  const snapshot = useCountry
    ? applyCountryOverrideSnapshot(computeStatusSnapshot(visible))
    : computeStatusSnapshot(visible);

  const signals = useCountry
    ? applyCountryOverrideSignals(computePlanningSignals(visible))
    : computePlanningSignals(visible);

  const totalAssignedCount = useCountry ? countryKpiOverrides.total : visible.length;

  // ── Cluster-setup directory (on the uploaded/intake schools — the cluster
  //    workflow universe), scoped to the viewer's supervision chain. ──
  const seesAll =
    currentUser.role === "Admin" || currentUser.role === "CountryDirector" ||
    currentUser.role === "RVP" || currentUser.role === "ImpactAssessment";
  const staffScope = seesAll ? null : visibleStaffIds(currentUser.staffId, currentUser.role);
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
  const clusterDirectorySchools: DirectorySchoolVM[] = intakeSchools
    .filter((s) => {
      if (seesAll) return true;
      const r = resolveOwner(s.assignedCceo);
      return r.status === "matched" ? staffScope!.has(r.staffId) : true;
    })
    .map((s) => {
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
      };
    });
  // Partner/HR cannot add schools to clusters; everyone else with directory
  // access can (server actions re-check).
  const canManageClusters = ["CCEO", "CountryProgramLead", "CountryDirector", "ImpactAssessment", "Admin"]
    .includes(currentUser.role);

  return (
    <ResponsiveDashboard mobile={<SchoolsView intelligenceSchools={ordered} />} desktop={
    <>
      <SchoolsHeader />
        <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
          {/* KPI Row — 9 cards (CCEO-scoped or country-scoped per role) */}
          <SchoolKpiRow kpis={kpis} />

          {/* Cluster setup — the next required step after upload. Every
              unclustered school can be added to a cluster right here. */}
          <SchoolsClusterDirectory schools={clusterDirectorySchools} canManage={canManageClusters} />

          {/* Intelligence hero — Priority / Most Improved / Struggling
              tabs. Replaces the old directory-table-with-side-panel
              layout because the questions CDs / PLs / IAs / CCEOs open
              this page to ask are intelligence questions, not browsing
              questions. The full directory table still lives below for
              power-users who need it. */}
          <SchoolsIntelligence schools={ordered} />

          {/* Full directory — kept below the intelligence tabs for
              cases where the user already knows the school name and
              wants the raw row. Spans full width now that the urgent
              panel folded into the Priority tab above. */}
          <SchoolsDirectorySection
            schools={ordered}
            totalAssignedCount={totalAssignedCount}
          />

          {/* Saved clusters — created from the directory above, consumed by Planning */}
          <ClustersCard clusters={clusters} />

          {/* Status snapshot + Planning signals */}
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
