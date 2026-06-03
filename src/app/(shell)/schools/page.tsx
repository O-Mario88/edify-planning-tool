import { SchoolsHeader } from "@/components/schools/SchoolsHeader";
import { SchoolKpiRow } from "@/components/schools/SchoolKpiRow";
import { SchoolStatusSnapshot } from "@/components/schools/SchoolStatusSnapshot";
import { PlanningReviewSignals } from "@/components/schools/PlanningReviewSignals";
import { SchoolQuickActions } from "@/components/schools/SchoolQuickActions";
import { SchoolsClusterDirectory } from "@/components/cluster/SchoolsClusterDirectory";
import type { DirectorySchoolVM, DirectoryClusterMatch } from "@/components/cluster/DirectoryClusterDrawer";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SchoolsView } from "@/components/mobile/views/SchoolsView";
import {
  clusterStatusOf,
  recommendClustersFor,
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

// School Directory = source of truth. KPIs, snapshot, signals and the directory
// itself are all computed from the uploaded schools (intakeSchools) via the
// canonical directory accessor — no separate schoolsMock universe on desktop.
// (The mobile view still renders the legacy SchoolRow set for now.)
export default async function SchoolsDashboard() {
  const currentUser = toCurrentUser(await getCurrentUser());

  // Canonical directory: the viewer's uploaded schools (scoped to their chain).
  const records = directoryRecords(currentUser.staffId, currentUser.role);
  const kpis = directoryKpis(records);
  const snapshot = directoryStatusSnapshot(records);
  const signals = directoryPlanningSignals(records);

  // Mobile view still uses the legacy SchoolRow set (separate migration).
  const ordered = [...getVisibleSchools(currentUser)].sort(priorityOrder);

  // ── Cluster-setup directory rows (same master, enriched with workflow state). ──
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
  const clusterDirectorySchools: DirectorySchoolVM[] = records
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

          {/* The directory itself — the uploaded schools (source of truth),
              with their workflow stage + the next action launched from here. */}
          <SchoolsClusterDirectory schools={clusterDirectorySchools} canManage={canManageClusters} />

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
