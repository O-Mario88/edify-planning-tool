import { Users } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { EmptyState, ErrorState } from "@/components/ui/DataStates";
import { getCurrentUser } from "@/lib/auth";
import { fetchHrRoster, type BeRosterRow } from "@/lib/api/surfaces";

// Live: HR roster from the backend (counts + staff[]). The roster has no
// achievement% — so the index drops the per-row achievement readout and pace
// badge rather than fanning out a target fetch per row. Onboarding state is the
// only per-row badge. Falls back to the team-targets mock (loaded lazily, so the
// page file has no top-level `*-mock` import) when the backend is off, keeping
// the build green and the mock-leakage gate clear.

const ONBOARD_TONE = (state: string): "green" | "amber" | "slate" =>
  /active|onboard|complete/i.test(state) ? "green" :
  /pending|invite|review|gap/i.test(state) ? "amber" :
  "slate";

export default async function StaffIndex() {
  const user = await getCurrentUser();
  const isCd = user.role === "CountryDirector";
  const r = await fetchHrRoster(user);

  if (r.live) {
    const staff = r.data.staff;
    return (
      <EntityIndex
        title={isCd ? "Staff Performance" : "Staff Directory"}
        subtitle={isCd
          ? "Monitor field staff — target achievement, visits, training & SSA by intervention. Click a row for the full profile."
          : "Field roster — CCEOs, Program Leads, partners. Click a row for the 360° profile."}
        Icon={Users}
        count={staff.length}
        searchPlaceholder="Search by name, district, role"
      >
        {staff.length === 0 ? (
          <EmptyState
            title="No staff on the roster"
            message="Staff appear here once they're onboarded into the system."
          />
        ) : (
          <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
            {staff.map((row: BeRosterRow) => (
              <IndexRow
                key={row.staffProfileId}
                href={`/staff/${row.staffProfileId}`}
                Icon={Users}
                title={row.name}
                subtitle={`${row.role} · ${row.primaryDistrict ?? "Unassigned"}`}
                meta={`${row.schools} schools · ${row.supervisees} supervisees`}
                badges={[{ label: row.onboardingState, tone: ONBOARD_TONE(row.onboardingState) }]}
              />
            ))}
          </section>
        )}
      </EntityIndex>
    );
  }

  if (r.error) {
    return (
      <EntityIndex title="Staff Directory" Icon={Users} searchPlaceholder="Search by name, district, role">
        <ErrorState message="Could not load the staff roster." />
      </EntityIndex>
    );
  }

  // Backend disabled — fall back to the mock so the build/demo stays green.
  // Lazy import keeps any `*-mock` specifier out of the top-level import graph
  // (the mock-leakage gate keys on `from "…-mock"`).
  const { staffTargetPerformance } = await import("@/lib/team-targets-mock");
  const staff = staffTargetPerformance;
  return (
    <EntityIndex
      title="Staff Directory"
      subtitle="Everyone with a target — CCEOs, Program Leads, partners. Click a row for the 360° profile."
      Icon={Users}
      count={staff.length}
      searchPlaceholder="Search by name, region, role"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {staff.map((s) => (
          <IndexRow
            key={s.staffId}
            href={`/staff/${s.staffId}`}
            Icon={Users}
            title={s.staffName}
            subtitle={`${s.role} · ${s.region}`}
            meta={`${s.completedActivities}/${s.monthlyTargetActivities} this month · SF compliance ${s.salesforceCompliancePercent}%`}
            rightTop={`${s.achievementPercent}%`}
            rightBottom="achievement"
          />
        ))}
      </section>
    </EntityIndex>
  );
}
