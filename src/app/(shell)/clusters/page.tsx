import Link from "next/link";
import { Network, BarChart3, History, ShieldCheck, FileText, Building2 } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { UnclusteredSchoolsBanner } from "@/components/planning/UnclusteredSchoolsBanner";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { CreateClusterButton } from "@/components/cluster/CreateClusterButton";
import { LiveClusterList } from "@/components/cluster/LiveClusterList";
import { getCurrentUser } from "@/lib/auth";
import { clusterCountsFor } from "@/lib/cluster/cluster-core";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { partners } from "@/lib/partner/partner-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";

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
  const counts = clusterCountsFor(scopedSchools);
  const unclusteredCount = counts.unclustered;

  // Partner picker options for delegating a cluster to a partner. Stable
  // config-ish input passed into the live list (no backend partner endpoint).
  const partnerOptions = partners.map((p) => ({ id: p.id, name: p.name }));

  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      searchPlaceholder="Search clusters"
    >
      <div className="mb-3 space-y-3">
        <UnclusteredSchoolsBanner count={unclusteredCount} />
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-stretch">
          <ClusterReadinessCard
            clustered={counts.clustered}
            unclustered={counts.unclustered}
            needsReview={counts.needsReview}
            title="Cluster setup readiness"
          />
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
      <LiveClusterList partners={partnerOptions} />
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
