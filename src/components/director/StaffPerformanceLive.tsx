import Link from "next/link";
import { ArrowUpRight, UserCog } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { getCurrentUser } from "@/lib/auth";
import { fetchHrRoster } from "@/lib/api/surfaces";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { StaffPerformanceSummary } from "./StaffPerformanceSummary";

export async function StaffPerformanceLive() {
  if (isMockAllowed()) return <StaffPerformanceSummary />;

  const user = await getCurrentUser();
  const roster = await fetchHrRoster(user);
  if (!roster.live) return <InsufficientData surface="staff performance" />;

  const staff = roster.data.staff.filter((s) => s.role === "CCEO" || s.role === "CountryProgramLead");
  const active = staff.filter((s) => s.active).length;
  const metrics: MetricCell[] = [
    { key: "total", label: "Field staff", value: staff.length },
    { key: "active", label: "Active", value: active, tone: "good" },
    { key: "cceos", label: "CCEOs", value: staff.filter((s) => s.role === "CCEO").length },
    { key: "pls", label: "Program Leads", value: staff.filter((s) => s.role === "CountryProgramLead").length },
  ];

  return (
    <SectionCard
      icon={<UserCog size={13} />}
      title="Staff Performance"
      actions={
        <Link href="/staff" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Full roster <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-4" />
      <ul className="mt-2.5 divide-y divide-[var(--color-edify-divider)]">
        {staff.slice(0, 5).map((s) => (
          <li key={s.staffProfileId} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-bold tracking-tight truncate">{s.name}</div>
              <div className="text-[11px] muted truncate">
                {s.role} · {s.primaryDistrict ?? "Unassigned"} · {s.schools} schools
              </div>
            </div>
            <Link
              href={`/staff/${s.staffProfileId}`}
              className="shrink-0 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
            >
              Targets &amp; SSA →
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] muted leading-snug">
        Drill into any staff member for visit/training/core targets and SSA movement in the interventions they supported.
      </p>
    </SectionCard>
  );
}
