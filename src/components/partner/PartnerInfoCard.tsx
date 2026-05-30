// PartnerInfoCard — the "who am I, what's my contract" header card on
// the partner dashboard. Reads like a contact card: organisation name +
// status pill + mission, partner code beneath, and a 5-up grid of
// contract facts (focal person, districts, schools, period, Edify focal).

import { User, MapPin, Building2, Calendar, UserCheck } from "lucide-react";
import type { PartnerOrgInfo } from "@/lib/partner/partner-dashboard-mock";

export function PartnerInfoCard({ org }: { org: PartnerOrgInfo }) {
  return (
    <section className="card p-3.5">
      <div className="flex flex-col lg:flex-row gap-5 lg:items-start">
        {/* Identity block */}
        <div className="flex gap-3.5 min-w-0 lg:max-w-[42%]">
          <div className="h-12 w-12 shrink-0 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-body-lg font-extrabold">
            {org.shortInitials}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[16px] font-extrabold tracking-tight">{org.name}</h2>
              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {org.status}
              </span>
            </div>
            <p className="text-body muted mt-1.5 leading-snug">
              <span className="font-bold text-[var(--color-edify-text)]">Our Mission:</span>{" "}
              {org.mission}
            </p>
            <p className="text-[11.5px] muted mt-1.5">
              Partner Code: <span className="font-semibold text-[var(--color-edify-text)]">{org.partnerCode}</span>
            </p>
          </div>
        </div>

        {/* Contract facts grid */}
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3.5">
          <Fact
            Icon={User}
            label="Focal Person"
            value={org.focalPerson.name}
            sub={org.focalPerson.phone}
          />
          <Fact
            Icon={MapPin}
            label="Assigned Districts"
            value={org.assignedDistricts.join(", ")}
          />
          <Fact
            Icon={Calendar}
            label="Contract Period"
            value={`${org.contract.start} - ${org.contract.end}`}
            sub={`(${org.contract.monthsLabel})`}
          />
          <Fact
            Icon={Building2}
            label="Assigned Schools"
            value={`${org.assignedSchoolsCount} schools`}
          />
          <Fact
            Icon={UserCheck}
            label="Edify Focal Person"
            value={org.edifyFocalPerson.name}
            sub={org.edifyFocalPerson.phone}
          />
        </div>
      </div>
    </section>
  );
}

function Fact({
  Icon, label, value, sub,
}: {
  Icon: typeof User;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex items-start gap-2.5 min-w-0">
      <span className="mt-0.5 grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
        <Icon size={13} />
      </span>
      <div className="min-w-0">
        <div className="text-caption uppercase tracking-wide font-bold muted">{label}</div>
        <div className="text-body font-extrabold text-[var(--color-edify-text)] truncate">{value}</div>
        {sub && <div className="text-[11px] muted">{sub}</div>}
      </div>
    </div>
  );
}
