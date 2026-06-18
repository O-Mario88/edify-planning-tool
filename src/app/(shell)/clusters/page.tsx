import Link from "next/link";
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

export default async function ClustersIndex() {
  // Cluster-first: surface the viewer's cluster-setup readiness + unclustered
  // backlog at the top of the clusters hub, with jumps into the workspace,
  // analytics, and audit.
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
  // The setup-readiness counts, unclustered banner, and the CCEO cluster board
  // all derive from in-memory intake mock (intakeSchools / directoryRecords), not
  // the live backend. The cluster directory below self-fetches /api/clusters and
  // stays. Gate only the mock-derived surfaces so production shows no fabricated
  // counts.
  const mockOk = isMockAllowed();
  const counts = clusterCountsFor(scopedSchools);
  const unclusteredCount = counts.unclustered;

  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      searchPlaceholder="Search clusters"
    >
      <div className="mb-3 space-y-3">
        {/* Mock-derived (intake counts) — withheld in production. */}
        {mockOk && <UnclusteredSchoolsBanner count={unclusteredCount} />}
        {/* CCEO: parish-fellowship view of THEIR clusters — SSA coverage,
            weakest interventions, discussion topics, next meeting (spec §11).
            Mock-derived; withheld in production. */}
        {mockOk && user.role === "CCEO" && (
          <CceoClusterBoard staffId={user.staffId} role={user.role} />
        )}
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-stretch">
          {mockOk ? (
            <ClusterReadinessCard
              clustered={counts.clustered}
              unclustered={counts.unclustered}
              needsReview={counts.needsReview}
              title="Cluster setup readiness"
            />
          ) : (
            <div /> /* keep the grid's first column so the nav stays right-aligned */
          )}
          <nav className="card rounded-2xl p-3 flex md:flex-col gap-2 justify-center">
            <div className="md:mb-1"><CreateClusterButton /></div>
            <ClusterHubLink href="/schools" Icon={Building2} label="School directory" />
            <ClusterHubLink href="/clusters/analytics" Icon={BarChart3} label="Cluster analytics" />
            <ClusterHubLink href="/clusters/reports" Icon={FileText} label="Impact report" />
            <ClusterHubLink href="/clusters/audit" Icon={History} label="Audit trail" />
            <ClusterHubLink href="/data-intake/clusters" Icon={ShieldCheck} label="IA quality queue" />
          </nav>
        </div>
      </div>
      {/* Cluster dashboard — live clusters grouped by district; each expands to
          its school roster (ID, name, sub-county, phone, contact, SSA area). */}
      <ClusterDistrictDirectory />
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
