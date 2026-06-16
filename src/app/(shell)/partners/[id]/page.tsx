import { notFound } from "next/navigation";
import {
  Handshake,
  Activity,
  ShieldCheck,
  Target,
  MapPin,
  Building2,
  Calendar,
  ClipboardList,
  History,
} from "lucide-react";
import { EntityDetail, DetailKpi } from "@/components/shell/EntityDetail";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { partnerTargetPerformance } from "@/lib/team-targets-mock";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// ────────── Mock detail data ──────────
//
// These are hand-typed sample rows. Production will pull them from
// partner-projects, partner-schools, and verification-history stores.

type ActiveProject = {
  name: string;
  status: "Active" | "Pending" | "Closed";
  schools: number;
  owner: string;
};

const ACTIVE_PROJECTS: ActiveProject[] = [
  { name: "Christian Discipleship Program", status: "Active",  schools: 8, owner: "Sarah Okello"      },
  { name: "Numeracy Foundations Roll-out",  status: "Active",  schools: 5, owner: "Daniel Mwangi"     },
  { name: "Headteacher Leadership Cohort",  status: "Pending", schools: 4, owner: "Aisha Dar"         },
  { name: "Teaching Environment Audit",     status: "Active",  schools: 6, owner: "Grace Nansubuga"   },
];

const SCHOOLS_SERVED: { name: string; district: string }[] = [
  { name: "St. Mary's Primary",      district: "Kampala" },
  { name: "Wakiso Junior School",    district: "Wakiso"  },
  { name: "Mukono Community School", district: "Mukono"  },
  { name: "Jinja Hope Academy",      district: "Jinja"   },
  { name: "Mbale Light Primary",     district: "Mbale"   },
  { name: "Kabale Christian School", district: "Kabale"  },
];

const RECENT_VISITS: {
  date: string;
  school: string;
  purpose: string;
  verified: "Verified" | "Submitted" | "Pending";
}[] = [
  { date: "May 6, 2025",  school: "St. Mary's Primary",      purpose: "SSA follow-up coaching", verified: "Verified"  },
  { date: "May 2, 2025",  school: "Wakiso Junior School",    purpose: "Quarterly review",       verified: "Verified"  },
  { date: "Apr 28, 2025", school: "Mukono Community School", purpose: "Teaching audit",         verified: "Submitted" },
  { date: "Apr 24, 2025", school: "Jinja Hope Academy",      purpose: "Headteacher training",   verified: "Pending"   },
  { date: "Apr 20, 2025", school: "Mbale Light Primary",     purpose: "Cluster meeting",        verified: "Verified"  },
];

const VERIFICATION_HISTORY: { date: string; result: "Pass" | "Conditional" | "Fail"; auditor: string }[] = [
  { date: "Mar 15, 2025", result: "Pass",        auditor: "Impact Assessment — N. Kintu" },
  { date: "Nov 12, 2024", result: "Conditional", auditor: "Impact Assessment — B. Lumumba" },
  { date: "Jun 02, 2024", result: "Pass",        auditor: "Impact Assessment — J. Okello" },
];

export default async function PartnerDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Partner detail is 100% hand-typed mock (same 3 projects/14 schools/78 visits
  // for every partner). Withhold until backed by real Partner records.
  if (!isMockAllowed()) return <InsufficientData surface="partner detail" />;
  const p = partnerTargetPerformance.find((x) => x.partnerId === id);
  if (!p) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",     href: "/dashboard" },
        { label: "Partners", href: "/partners" },
        { label: p.partner },
      ]}
      title={p.partner}
      subtitle={`${p.region} · ${p.certificationStatus} · ${p.risk} risk profile`}
      Icon={Handshake}
      badge={
        p.certificationStatus === "Certified"
          ? { tone: "green", label: "Certified" }
          : p.certificationStatus === "Pending"
            ? { tone: "amber", label: "Cert. Pending" }
            : { tone: "rose", label: "Not Certified" }
      }
    >
      {/* KPI row — meaningful operational metrics */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Active Projects"      value="3"   caption="In delivery this FY"     Icon={Activity}    tone="edify"  />
        <DetailKpi label="Schools Served"       value="14"  caption="Across 6 districts"      Icon={Building2}   tone="violet" />
        <DetailKpi label="Verified Visits (FY)" value="78"  caption="Impact-assessed"         Icon={ShieldCheck} tone="green"  />
        <DetailKpi label="Capacity Utilization" value="64%" caption="Completed ÷ assigned"    Icon={Target}      tone="amber"  />
      </section>

      <div className="space-y-4">
        {/* Active Projects */}
        <SectionCard
          icon={<ClipboardList size={13} />}
          title="Active Projects"
          subtitle="Programs this partner is currently delivering, with the lead owner on each."
        >
          <div className="overflow-x-auto">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Project</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-right">Schools</th>
                  <th scope="col" className="text-left">Owner</th>
                </tr>
              </thead>
              <tbody>
                {ACTIVE_PROJECTS.map((row) => (
                  <tr key={row.name}>
                    <td className="text-body font-semibold whitespace-nowrap">{row.name}</td>
                    <td>
                      <StatusBadge>{row.status}</StatusBadge>
                    </td>
                    <td className="text-right tabular text-body font-extrabold">{row.schools}</td>
                    <td className="text-[12px] muted whitespace-nowrap">{row.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        {/* Schools served */}
        <SectionCard
          icon={<Building2 size={13} />}
          title="Schools served"
          subtitle="Schools currently engaged with this partner across the active districts."
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
            {SCHOOLS_SERVED.map((s) => (
              <div
                key={s.name}
                className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-3 py-2.5"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-6 h-6 rounded-md grid place-items-center bg-white text-[var(--color-edify-primary)] shrink-0">
                    <Building2 size={12} />
                  </span>
                  <div className="text-body font-extrabold tracking-tight truncate">{s.name}</div>
                </div>
                <div className="text-caption muted inline-flex items-center gap-1">
                  <MapPin size={10} />
                  {s.district}
                </div>
              </div>
            ))}
          </div>
        </SectionCard>

        {/* Recent visits */}
        <SectionCard
          icon={<Calendar size={13} />}
          title="Recent visits"
          subtitle="Most recent in-school visits delivered by this partner."
        >
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {RECENT_VISITS.map((v, i) => (
              <li key={i} className="flex items-center gap-3 py-2.5">
                <span className="w-9 h-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                  <Calendar size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{v.school}</div>
                  <div className="text-[11px] muted truncate">
                    {v.date} · {v.purpose}
                  </div>
                </div>
                <StatusBadge>{v.verified}</StatusBadge>
              </li>
            ))}
          </ul>
        </SectionCard>

        {/* Verification history */}
        <SectionCard
          icon={<History size={13} />}
          title="Verification history"
          subtitle="Past Impact Assessment audits and outcomes."
        >
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {VERIFICATION_HISTORY.map((h, i) => (
              <li key={i} className="flex items-center gap-3 py-2.5">
                <span className="w-9 h-9 rounded-md bg-violet-100 text-violet-700 grid place-items-center shrink-0">
                  <ShieldCheck size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{h.auditor}</div>
                  <div className="text-[11px] muted truncate">{h.date}</div>
                </div>
                <StatusBadge tone={h.result === "Pass" ? "green" : h.result === "Conditional" ? "amber" : "red"}>
                  {h.result}
                </StatusBadge>
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>
    </EntityDetail>
  );
}
