import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { CheckCircle2, AlertOctagon, Footprints } from "lucide-react";
import { planItems } from "@/lib/mobile-mock";

// Visits are derived from PlanItems whose type is "Visit" or "Follow-Up
// Visit". Production would have a dedicated `visits` table; for now the
// same plan store covers both surfaces.
export default function VisitsIndex() {
  const visits = planItems.filter((p) => p.type === "Visit" || p.type === "Follow-Up Visit");

  return (
    <EntityIndex
      title="Visits"
      subtitle="Every school visit on your plan, including verified, in-progress, and awaiting Salesforce ID."
      Icon={Footprints}
      count={visits.length}
      searchPlaceholder="Search by school, cluster"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {visits.map((v) => (
          <IndexRow
            key={v.id}
            href={`/plans/${v.id}`}
            Icon={v.status === "Verified" ? CheckCircle2 : v.status === "Awaiting SF ID" ? AlertOctagon : Footprints}
            iconBg={v.status === "Verified" ? "bg-emerald-100" : v.status === "Awaiting SF ID" ? "bg-rose-100" : "bg-sky-100"}
            iconText={v.status === "Verified" ? "text-emerald-700" : v.status === "Awaiting SF ID" ? "text-rose-700" : "text-sky-700"}
            title={`${v.type} — ${v.context}`}
            subtitle={`${v.weekLabel} · ${v.date}`}
            badges={[{
              label: v.status,
              tone: v.status === "Verified" ? "green" : v.status === "Awaiting SF ID" ? "rose" : v.status === "In Progress" ? "blue" : "amber",
            }]}
          />
        ))}
      </section>
    </EntityIndex>
  );
}
