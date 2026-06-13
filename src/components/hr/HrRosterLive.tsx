// HrRosterLive — the real staff roster from the backend (StaffProfile + role +
// onboarding state + portfolio size). Server component: calls the HR surface
// directly, role-scoped. Renders nothing when the backend is off so the HR
// dashboard keeps its aggregated mock view.

import { Users, MapPin, School2, GitBranch } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchHrRoster } from "@/lib/api/surfaces";

const ROLE_LABEL: Record<string, string> = {
  CCEO: "CCEO", CountryProgramLead: "Program Lead", CountryDirector: "Country Director",
  RVP: "RVP", ImpactAssessment: "Impact Assessment", ProgramAccountant: "Accountant",
  HumanResource: "HR", ProjectCoordinator: "Project Coordinator", Admin: "Admin",
};

export async function HrRosterLive() {
  const user = await getCurrentUser();
  const r = await fetchHrRoster(user);
  if (!r.live) return null;
  const { counts, staff } = r.data;

  const byRole = new Map<string, number>();
  for (const s of staff) byRole.set(s.role, (byRole.get(s.role) ?? 0) + 1);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Users size={14} className="text-[var(--color-edify-primary)]" /> Staff roster
          </h3>
          <p className="text-[11.5px] muted">{counts.total} staff · {counts.active} active · {counts.pending} onboarding</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      {/* Role distribution */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {[...byRole.entries()].sort((a, b) => b[1] - a[1]).map(([role, n]) => (
          <span key={role} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md bg-[var(--color-edify-soft)]/60 text-[11px] font-semibold">
            {ROLE_LABEL[role] ?? role} <span className="tabular font-extrabold text-[var(--color-edify-primary)]">{n}</span>
          </span>
        ))}
      </div>

      {/* Roster table */}
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full text-[12px] min-w-[560px]">
          <thead>
            <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th scope="col" className="py-2 pr-2">Staff</th>
              <th scope="col" className="py-2 px-2">Role</th>
              <th scope="col" className="py-2 px-2">District</th>
              <th scope="col" className="py-2 px-2 text-right">Schools</th>
              <th scope="col" className="py-2 px-2 text-right">Supervisees</th>
              <th scope="col" className="py-2 pl-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {staff.slice(0, 30).map((s) => (
              <tr key={s.staffProfileId} className="hover:bg-[var(--color-edify-soft)]/30">
                <td className="py-2 pr-2 font-extrabold truncate max-w-[180px]">{s.name}</td>
                <td className="py-2 px-2 muted">{ROLE_LABEL[s.role] ?? s.role}</td>
                <td className="py-2 px-2 muted">
                  <span className="inline-flex items-center gap-1"><MapPin size={10} />{s.primaryDistrict ?? "—"}</span>
                </td>
                <td className="py-2 px-2 text-right tabular">
                  <span className="inline-flex items-center gap-1 justify-end"><School2 size={10} className="text-[var(--color-edify-muted)]" />{s.schools}</span>
                </td>
                <td className="py-2 px-2 text-right tabular">
                  <span className="inline-flex items-center gap-1 justify-end"><GitBranch size={10} className="text-[var(--color-edify-muted)]" />{s.supervisees}</span>
                </td>
                <td className="py-2 pl-2">
                  <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold capitalize ${s.onboardingState === "active" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                    {s.onboardingState}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {staff.length > 30 && <p className="text-[11px] muted mt-2">Showing 30 of {staff.length} staff.</p>}
    </section>
  );
}
