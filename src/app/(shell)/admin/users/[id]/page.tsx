import { notFound } from "next/navigation";
import { Users } from "lucide-react";
import { EntityDetail, DetailFacts } from "@/components/shell/EntityDetail";
import { DEMO_USERS } from "@/lib/auth-public";
import { orgStaff, supervisorOf } from "@/lib/org/supervision";
import { computeActivationReadiness } from "@/lib/org/staff-activation";
import { districtNameOf } from "@/lib/geography";

// Resolves a user from BOTH sources: seeded demo accounts (keyed by email) and
// runtime-created staff (keyed by staffId via the org roster), so a detail link
// works whether it points at an email or a staffId — created staff no longer 404.
export default async function AdminUserDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const key = decodeURIComponent(id);

  const demo = DEMO_USERS[key];
  const staff = orgStaff(key);
  if (!demo && !staff) return notFound();

  const name = demo?.name ?? staff!.name;
  const email = demo?.email ?? staff?.email ?? "—";
  const role = (demo?.role ?? staff!.role) as string;
  const district = staff?.district ?? (staff?.primaryDistrictId ? districtNameOf(staff.primaryDistrictId) : undefined);
  const readiness = staff ? computeActivationReadiness(staff.staffId) : null;
  const supervisor = staff ? supervisorOf(staff.staffId) : undefined;

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",  href: "/dashboard" },
        { label: "Admin", href: "/admin" },
        { label: "Users", href: "/admin/users" },
        { label: name },
      ]}
      title={name}
      subtitle={email}
      Icon={Users}
      badge={{ tone: readiness && readiness.status !== "Active" ? "amber" : "edify", label: readiness?.status ?? role }}
    >
      <DetailFacts
        rows={[
          { label: "Email",  value: email },
          { label: "Role",   value: role.replace(/([A-Z])/g, " $1").trim() },
          ...(district ? [{ label: "Primary district", value: district }] : []),
          ...(supervisor ? [{ label: "Supervisor", value: supervisor.name }] : []),
          { label: "Status", value: readiness?.status ?? "Active" },
        ]}
      />

      {readiness && readiness.requiredCount > 0 && (
        <section className="card p-3.5">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight">Onboarding readiness</h2>
            <span className="text-[11px] font-extrabold tabular muted">{readiness.metCount}/{readiness.requiredCount} gates met</span>
          </div>
          <div className="h-2 rounded-full bg-[var(--color-edify-soft)]/70 overflow-hidden mb-2.5">
            <div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${Math.round((readiness.metCount / readiness.requiredCount) * 100)}%` }} />
          </div>
          {readiness.gaps.length > 0 ? (
            <ul className="space-y-1.5">
              {readiness.gaps.map((g) => (
                <li key={g} className="text-[12px] flex items-center gap-2 text-amber-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> {g}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-emerald-700 font-semibold">All onboarding gates met — staff is Active.</p>
          )}
        </section>
      )}

      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Permissions</h2>
        <p className="text-[11.5px] muted">
          Permissions are inherited from the user&apos;s role. To change them, edit the role assignment.
          Role changes are audited and require a second-Admin approval in production.
        </p>
      </section>
    </EntityDetail>
  );
}
