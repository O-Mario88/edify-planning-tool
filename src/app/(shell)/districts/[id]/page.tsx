import { notFound } from "next/navigation";
import Link from "next/link";
import {
  MapPin,
  Building2,
  Activity,
  Wallet,
  ShieldCheck,
  TrendingUp,
  Calendar,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { districtRollups } from "@/lib/workflow-mock";

// Districts are slug-cased so links can use them as URL segments.
function slug(s: string): string {
  return s.toLowerCase().replace(/\s+/g, "-");
}

export default async function DistrictDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const district = districtRollups.find((d) => slug(d.district) === id);
  if (!district) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",      href: "/dashboard" },
        { label: "Districts", href: "/districts" },
        { label: district.district },
      ]}
      title={district.district}
      subtitle={`District rollup — ${district.schools} schools (${district.active} active · ${district.inactive} inactive). CCEO lead: ${district.cceo}.`}
      Icon={MapPin}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Schools"           value={String(district.schools)} caption={`${district.active} active`}              Icon={Building2}  tone="edify" />
        <DetailKpi label="SSA Completed"     value={`${district.ssaCompletedPct}%`} caption="Of assessed schools"                Icon={ShieldCheck} tone={district.ssaCompletedPct >= 75 ? "green" : "amber"} />
        <DetailKpi label="Valid Visit %"     value={`${district.validVisitPct}%`}   caption="Verified visits portion"            Icon={Activity}    tone={district.validVisitPct >= 80 ? "green" : "amber"} />
        <DetailKpi label="Monthly Target %"  value={`${district.monthlyTargetPct}%`} caption="Pacing toward target"              Icon={TrendingUp}  tone={district.monthlyTargetPct >= 80 ? "green" : district.monthlyTargetPct >= 60 ? "amber" : "rose"} />
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <DetailFacts
            rows={[
              { label: "District",      value: district.district },
              { label: "Assigned CCEO", value: district.cceo },
              { label: "Schools",       value: `${district.schools} total · ${district.active} active · ${district.inactive} inactive` },
              { label: "Verified %",    value: `${district.verifiedPct}%` },
              { label: "Valid Visits %",value: `${district.validVisitPct}%` },
              { label: "SSA %",         value: `${district.ssaCompletedPct}%` },
              { label: "Monthly Target",value: `${district.monthlyTargetPct}%` },
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
              <Link href="/dashboards/accountant" className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Wallet size={13} /> Fund flow in this district
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
