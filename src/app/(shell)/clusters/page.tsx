import Link from "next/link";
import { Network, BarChart3, History, ShieldCheck } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { clustersMock } from "@/lib/schools-mock";
import { UnclusteredSchoolsBanner } from "@/components/planning/UnclusteredSchoolsBanner";
import { ClusterReadinessCard } from "@/components/cluster/ClusterReadinessCard";
import { getCurrentUser } from "@/lib/auth";
import { clusterCountsFor } from "@/lib/cluster/cluster-core";
import { intakeSchools } from "@/lib/intake/intake-mock";
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

  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      count={clustersMock.length}
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
            <ClusterHubLink href="/clusters/assign" Icon={Network} label="Assign workspace" />
            <ClusterHubLink href="/clusters/analytics" Icon={BarChart3} label="Cluster analytics" />
            <ClusterHubLink href="/clusters/audit" Icon={History} label="Audit trail" />
            <ClusterHubLink href="/data-intake/clusters" Icon={ShieldCheck} label="IA quality queue" />
          </nav>
        </div>
      </div>
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {clustersMock.map((c) => (
          <IndexRow
            key={c.id}
            href={`/clusters/${c.id}`}
            Icon={Network}
            title={c.name}
            subtitle={`${c.schoolIds.length} schools · ${c.region ?? "—"} · ${c.district ?? "—"}`}
            meta={c.description}
            rightTop={c.shippingAddress ?? "—"}
            rightBottom="shipping hub"
          />
        ))}
      </section>
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
