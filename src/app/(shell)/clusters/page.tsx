import { Network } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { clustersMock } from "@/lib/schools-mock";
import { UnclusteredSchoolsBanner } from "@/components/planning/UnclusteredSchoolsBanner";
import { getCurrentUser } from "@/lib/auth";
import { unclusteredSchools } from "@/lib/cluster/cluster-core";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";

export default async function ClustersIndex() {
  // Cluster-first: surface the viewer's unclustered backlog at the top of the
  // clusters hub with a jump into the assignment workspace.
  const user = await getCurrentUser();
  const seesAll =
    user.role === "Admin" || user.role === "CountryDirector" ||
    user.role === "RVP" || user.role === "ImpactAssessment";
  const scope = seesAll ? null : visibleStaffIds(user.staffId, user.role);
  const unclusteredCount = unclusteredSchools().filter((s) => {
    if (seesAll) return true;
    const r = resolveOwner(s.assignedCceo);
    return r.status === "matched" ? scope!.has(r.staffId) : true;
  }).length;

  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      count={clustersMock.length}
      searchPlaceholder="Search clusters"
    >
      <div className="mb-3">
        <UnclusteredSchoolsBanner count={unclusteredCount} />
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
