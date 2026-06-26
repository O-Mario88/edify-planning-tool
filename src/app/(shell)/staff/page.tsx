import { Users } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { EmptyState, ErrorState } from "@/components/ui/DataStates";
import { getCurrentUser } from "@/lib/auth";
import { fetchHrRoster, type BeRosterRow } from "@/lib/api/surfaces";

// Live: HR roster from the backend (counts + staff[]). The roster has no
// achievement% — so the index drops the per-row achievement readout and pace
// badge rather than fanning out a target fetch per row. Onboarding state is the
// only per-row badge. Backend-only: no mock fallback — a disabled/unreachable
// backend shows a clear error so the failure is visible, not hidden behind
// fabricated rows.

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

  // Backend off or unreachable — show a clear error. No mock fallback: faking
  // a roster would hide an outage behind fabricated staff rows.
  return (
    <EntityIndex title="Staff Directory" Icon={Users} searchPlaceholder="Search by name, district, role">
      <ErrorState message="Could not load the staff roster." />
    </EntityIndex>
  );
}
