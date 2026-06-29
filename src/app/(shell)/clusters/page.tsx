import Link from "next/link";
export const dynamic = "force-dynamic";
import { Network, BarChart3, History, ShieldCheck, FileText, Building2 } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { UnclusteredSchoolsBanner } from "@/components/planning/UnclusteredSchoolsBanner";
import { CceoClusterBoard } from "@/components/cluster/CceoClusterBoard";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { CreateClusterButton } from "@/components/cluster/CreateClusterButton";
import { ClusterDistrictDirectory } from "@/components/cluster/ClusterDistrictDirectory";
import { getCurrentUser } from "@/lib/auth";
import { clusterCountsFor } from "@/lib/cluster/cluster-core";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";
import { isMockAllowed } from "@/lib/mock-policy";
import { isBackendEnabled } from "@/lib/api/backend";
import {
  fetchClusters,
  fetchAnalyticsDashboard,
  fetchBackendGeoByDistrict,
  type BeCluster,
} from "@/lib/api/surfaces";

export default async function ClustersIndex() {
  const user = await getCurrentUser();
  const seesAll =
    user.role === "Admin" || user.role === "CountryDirector" ||
    user.role === "RVP" || user.role === "ImpactAssessment";
  const scope = seesAll ? null : visibleStaffIds(user.staffId, user.role);
  const scopedSchools = intakeSchools.filter((s) => {
    if (seesAll) return true;
    const r = resolveOwner(s.assignedCceo);
    return r.status === "matched" ? scope!.has(r.staffId) : true;
  });
  const mockOk = isMockAllowed();
  const mockCounts = clusterCountsFor(scopedSchools);

  // Live backend: prefetch clusters + geo so create/list stay in sync on production.
  const bu = { email: user.email, role: user.role };
  let initialClusters: BeCluster[] | null = null;
  let initialClusterError: string | null = null;
  let geoByDistrict: Record<string, string[]> | undefined;
  let liveCounts: { clustered: number; unclustered: number; needsReview: number } | null = null;

  if (isBackendEnabled()) {
    const [clusterRes, dashRes, geo] = await Promise.all([
      fetchClusters(bu),
      fetchAnalyticsDashboard(bu),
      fetchBackendGeoByDistrict(bu),
    ]);
    if (clusterRes.live) {
      initialClusters = clusterRes.data;
      if (dashRes.live) {
        liveCounts = {
          clustered: dashRes.data.schools - dashRes.data.unclustered,
          unclustered: dashRes.data.unclustered,
          needsReview: 0,
        };
      }
    } else {
      initialClusterError = clusterRes.error ?? "Could not load clusters from edify-api.";
    }
    if (geo && Object.keys(geo).length) geoByDistrict = geo;
  }

  const counts = liveCounts ?? mockCounts;
  const unclusteredCount = liveCounts?.unclustered ?? mockCounts.unclustered;
  const showReadiness = mockOk || liveCounts !== null;

  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      searchPlaceholder="Search clusters"
    >
      <div className="mb-3 space-y-3">
        {(mockOk || liveCounts) && unclusteredCount > 0 && (
          <UnclusteredSchoolsBanner count={unclusteredCount} />
        )}
        {mockOk && user.role === "CCEO" && (
          <CceoClusterBoard staffId={user.staffId} role={user.role} />
        )}
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-stretch">
          {showReadiness ? (
            <ClusterReadinessCard
              clustered={counts.clustered}
              unclustered={counts.unclustered}
              needsReview={counts.needsReview}
              title="Cluster setup readiness"
            />
          ) : (
            <div />
          )}
          <nav className="card rounded-2xl p-3 flex md:flex-col gap-2 justify-center">
            <div className="md:mb-1"><CreateClusterButton geoByDistrict={geoByDistrict} /></div>
            <ClusterHubLink href="/schools" Icon={Building2} label="School directory" />
            <ClusterHubLink href="/clusters/analytics" Icon={BarChart3} label="Cluster analytics" />
            <ClusterHubLink href="/clusters/reports" Icon={FileText} label="Impact report" />
            <ClusterHubLink href="/clusters/audit" Icon={History} label="Audit trail" />
            <ClusterHubLink href="/data-intake/clusters" Icon={ShieldCheck} label="IA quality queue" />
          </nav>
        </div>
      </div>
      <ClusterDistrictDirectory
        initialClusters={initialClusters}
        initialError={initialClusterError}
      />
    </EntityIndex>
  );
}

function ClusterHubLink({
  href, Icon, label,
}: {
  href: string;
  Icon: typeof Network;
  label: string;
}) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-[12px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 transition-colors whitespace-nowrap"
    >
      <Icon size={14} className="text-[var(--color-edify-primary)]" />
      {label}
    </Link>
  );
}
