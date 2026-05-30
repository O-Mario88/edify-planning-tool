import { Network } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { clustersMock } from "@/lib/schools-mock";

export default function ClustersIndex() {
  return (
    <EntityIndex
      title="Clusters"
      subtitle="Groups of schools planned and delivered together. Drives routes, training cohorts, and partner assignments."
      Icon={Network}
      count={clustersMock.length}
      searchPlaceholder="Search clusters"
    >
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
