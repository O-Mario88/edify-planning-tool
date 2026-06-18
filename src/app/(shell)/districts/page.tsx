import { MapPin } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchDistrictRollups } from "@/lib/api/surfaces";

function slug(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "-");
}

export default async function DistrictsIndex() {
  // Live per-district rollups (real school counts + SSA health), scoped to the
  // caller. Falls back to an empty state only when the backend is unreachable.
  const user = await getCurrentUser();
  const res = await fetchDistrictRollups(user);
  if (!res.live)
    return (
      <ProductiveEmptyState
        Icon={MapPin}
        tone="info"
        title="District roll-ups aren't connected to live data yet"
        description="Per-district school counts and SSA health will appear here once the backend returns live roll-ups."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[
          { label: "Schools", href: "/schools" },
          { label: "Data room", href: "/analytics/data-room" },
        ]}
      />
    );
  const districts = res.data.districts;

  return (
    <EntityIndex
      title="Districts"
      subtitle="District-level rollups: schools, SSA completion, cluster coverage, and average SSA."
      Icon={MapPin}
      count={districts.length}
      searchPlaceholder="Search districts"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {districts.map((d) => (
          <IndexRow
            key={d.districtId}
            href={`/districts/${slug(d.district)}`}
            Icon={MapPin}
            title={d.district}
            subtitle={`${d.schools} schools${d.region ? ` · ${d.region}` : ""}`}
            meta={`SSA complete ${d.ssaPct}% · Avg SSA ${d.avgSsa}/10 · Clustered ${d.clustered}/${d.schools}`}
            rightTop={`${d.ssaPct}%`}
            rightBottom="SSA complete"
            badges={[
              { label: `${d.coreSchools} core`, tone: "green" },
              { label: d.unclustered > 0 ? `${d.unclustered} unclustered` : "all clustered", tone: d.unclustered > 0 ? "amber" : "green" },
            ]}
          />
        ))}
      </section>
    </EntityIndex>
  );
}
