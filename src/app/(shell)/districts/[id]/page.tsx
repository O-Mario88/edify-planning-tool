import { notFound } from "next/navigation";
import Link from "next/link";
import { MapPin, Building2, Activity, ShieldCheck, Star, Calendar } from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";
import { getCurrentUser } from "@/lib/auth";
import { fetchDistrictRollups } from "@/lib/api/surfaces";

// Districts are slug-cased so links can use them as URL segments.
function slug(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "-");
}

export default async function DistrictDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Live per-district rollup (real school counts + SSA health), scoped to the caller.
  const user = await getCurrentUser();
  const res = await fetchDistrictRollups(user);
  if (!res.live)
    return (
      <ProductiveEmptyState
        Icon={MapPin}
        tone="info"
        title="District detail isn't connected to live data yet"
        description="This district's school counts and SSA health will appear here once the backend returns live roll-ups."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[{ label: "Schools", href: "/schools" }]}
      />
    );
  const district = res.data.districts.find((d) => slug(d.district) === id);
  if (!district) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",      href: "/dashboard" },
        { label: "Districts", href: "/districts" },
        { label: district.district },
      ]}
      title={district.district}
      subtitle={`District rollup — ${district.schools} schools${district.region ? ` in ${district.region}` : ""} (${district.coreSchools} core · ${district.clientSchools} client).`}
      Icon={MapPin}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Schools"        value={String(district.schools)}     caption={`${district.coreSchools} core · ${district.clientSchools} client`} Icon={Building2}   tone="edify" />
        <DetailKpi label="SSA Complete"   value={`${district.ssaPct}%`}         caption={`${district.ssaDone}/${district.schools} schools`}                Icon={ShieldCheck} tone={district.ssaPct >= 75 ? "green" : "amber"} />
        <DetailKpi label="Avg SSA Score"  value={`${district.avgSsa}/10`}       caption="Across assessed schools"                                          Icon={Activity}    tone={district.avgSsa >= 7 ? "green" : district.avgSsa < 5 ? "rose" : "amber"} />
        <DetailKpi label="Clustered"      value={`${district.clustered}/${district.schools}`} caption={`${district.unclustered} unclustered`}             Icon={Star}        tone={district.unclustered === 0 ? "green" : "amber"} />
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <DetailFacts
            rows={[
              { label: "District",       value: district.district },
              { label: "Region",         value: district.region || "—" },
              { label: "Schools",        value: `${district.schools} total · ${district.coreSchools} core · ${district.clientSchools} client` },
              { label: "SSA complete",   value: `${district.ssaPct}% (${district.ssaDone}/${district.schools})` },
              { label: "Average SSA",    value: `${district.avgSsa}/10` },
              { label: "Cluster coverage", value: `${district.clustered} clustered · ${district.unclustered} unclustered` },
            ]}
          />
        </div>
        <div className="col-span-12 md:col-span-5 card p-3.5">
          <h3 className="text-[13px] font-extrabold tracking-tight">Quick actions</h3>
          <ul className="mt-2 space-y-2 text-[12px]">
            <li>
              <Link href="/schools" className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Building2 size={13} /> Schools in this district
              </Link>
            </li>
            <li>
              <Link href="/ssa" className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Activity size={13} /> SSA performance by intervention
              </Link>
            </li>
            <li>
              <Link href="/clusters" className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Star size={13} /> Clusters in this district
              </Link>
            </li>
            <li>
              <Link href="/calendar" className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Calendar size={13} /> District calendar
              </Link>
            </li>
          </ul>
        </div>
      </section>
    </EntityDetail>
  );
}
