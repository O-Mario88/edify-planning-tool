import { MapPin } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { districtRollups } from "@/lib/workflow-mock";

function slug(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "-");
}

export default function DistrictsIndex() {
  return (
    <EntityIndex
      title="Districts"
      subtitle="District-level rollups: schools, CCEOs, SSA completion, target pacing."
      Icon={MapPin}
      count={districtRollups.length}
      searchPlaceholder="Search districts"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {districtRollups.map((d) => (
          <IndexRow
            key={d.district}
            href={`/districts/${slug(d.district)}`}
            Icon={MapPin}
            title={d.district}
            subtitle={`${d.schools} schools · ${d.cceo}`}
            meta={`SSA ${d.ssaCompletedPct}% · Valid visit ${d.validVisitPct}% · Verified ${d.verifiedPct}%`}
            rightTop={`${d.monthlyTargetPct}%`}
            rightBottom="monthly target"
            badges={[
              { label: `${d.active} active`,   tone: "green" },
              { label: `${d.inactive} inactive`, tone: d.inactive > 0 ? "rose" : "slate" },
            ]}
          />
        ))}
      </section>
    </EntityIndex>
  );
}
