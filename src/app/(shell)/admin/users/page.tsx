import { Users } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { DEMO_USERS } from "@/lib/auth-public";
import { getCurrentUser } from "@/lib/auth";
import { createdOrgStaff } from "@/lib/org/supervision";
import { computeActivationReadiness } from "@/lib/org/staff-activation";
import { labelForRole } from "@/lib/intake/staff-creation-core";
import { AddStaffControl } from "@/components/admin/AddStaffControl";

// CD / HR own staff onboarding; Admin retained for the demo.
const STAFF_ADMIN_ROLES = ["CountryDirector", "HumanResource", "Admin"];

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Active: "green", Suspended: "slate", Inactive: "slate",
};

export default async function AdminUsersIndex() {
  const me = await getCurrentUser();
  const canAdd = STAFF_ADMIN_ROLES.includes(me.role);
  const demo = Object.values(DEMO_USERS);
  const created = createdOrgStaff();
  const existingEmails = [
    ...demo.map((u) => u.email),
    ...created.map((s) => s.email).filter((e): e is string => !!e),
  ];

  return (
    <EntityIndex
      title="Users & Roles"
      subtitle="Staff accounts, roles, supervisor, and onboarding status. Add staff to start the onboarding workflow — they're not operational until schools, primary district, and targets are connected."
      Icon={Users}
      count={demo.length + created.length}
      searchPlaceholder="Search users"
    >
      {canAdd && (
        <div className="flex justify-end">
          <AddStaffControl existingEmails={existingEmails} />
        </div>
      )}

      {created.length > 0 && (
        <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
          <header className="px-4 py-2.5 text-[12px] font-extrabold tracking-tight bg-[var(--color-edify-soft)]/40">
            Recently added — in onboarding
          </header>
          {created.map((s) => {
            // Status is COMPUTED by the activation engine, so it advances as
            // each later phase (schools, primary district, targets) lands.
            const r = computeActivationReadiness(s.staffId);
            const nextGap = r.gaps[0];
            return (
              <IndexRow
                key={s.staffId}
                href="/admin/users"
                Icon={Users}
                title={s.name}
                subtitle={`${s.email ?? ""} · ${labelForRole(s.role)}${s.district ? ` · ${s.district}` : ""}${nextGap ? ` · Next: ${nextGap}` : ""}`}
                meta={r.requiredCount > 0 ? `Onboarding ${r.metCount}/${r.requiredCount}` : undefined}
                badges={[{ label: r.status.replace(/([A-Z])/g, " $1").trim(), tone: STATUS_TONE[r.status] ?? "amber" }]}
              />
            );
          })}
        </section>
      )}

      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {demo.map((u) => (
          <IndexRow
            key={u.email}
            href={`/admin/users/${encodeURIComponent(u.email)}`}
            Icon={Users}
            title={u.name}
            subtitle={u.email}
            meta={u.role.replace(/([A-Z])/g, " $1").trim()}
            badges={[{ label: u.role, tone: "edify" }]}
          />
        ))}
      </section>
    </EntityIndex>
  );
}
