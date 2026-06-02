import Link from "next/link";
import { Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { DEMO_USERS } from "@/lib/auth-public";
import { getCurrentUser } from "@/lib/auth";
import { createdOrgStaff } from "@/lib/org/supervision";
import { computeActivationReadiness } from "@/lib/org/staff-activation";
import { labelForRole } from "@/lib/intake/staff-creation-core";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { AddStaffControl } from "@/components/admin/AddStaffControl";
import { AssignSchoolsControl } from "@/components/admin/AssignSchoolsControl";
import { PrimaryDistrictControl } from "@/components/admin/PrimaryDistrictControl";
import { AssignTargetProfileControl } from "@/components/admin/AssignTargetProfileControl";
import { ChangeSupervisorControl } from "@/components/admin/ChangeSupervisorControl";
import { defaultTargetProfileFor } from "@/lib/targets/staff-target-profile";
import { staffOnboardingHealth } from "@/lib/org/staff-health";
import { activeFinancialYear } from "@/lib/fy-engine";

// CD / HR own staff onboarding; Admin retained for the demo.
const STAFF_ADMIN_ROLES = ["CountryDirector", "HumanResource", "Admin"];

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Active: "green", Suspended: "slate", Inactive: "slate",
};

// Onboarding system-health summary — pending activation + the gaps to clear.
function StaffHealthStrip() {
  const h = staffOnboardingHealth();
  if (h.totalCreated === 0) return <div className="text-[11.5px] muted">No staff added through onboarding yet.</div>;
  const chips: Array<{ label: string; value: number; tone: "amber" | "rose" | "green" | "slate" }> = [
    { label: "Active", value: h.active, tone: "green" },
    { label: "In onboarding", value: h.pendingActivation, tone: h.pendingActivation > 0 ? "amber" : "slate" },
    { label: "No supervisor", value: h.missingSupervisor, tone: h.missingSupervisor > 0 ? "rose" : "slate" },
    { label: "Unassigned schools", value: h.unassignedSchools, tone: h.unassignedSchools > 0 ? "amber" : "slate" },
    { label: "Duplicate emails", value: h.duplicateEmails.length, tone: h.duplicateEmails.length > 0 ? "rose" : "slate" },
  ];
  const TONE = {
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-700",
    rose: "bg-rose-100 text-rose-700",
    slate: "bg-slate-100 text-slate-600",
  } as const;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {chips.map((c) => (
        <span key={c.label} className={cn("inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-extrabold", TONE[c.tone])}>
          {c.value} <span className="font-semibold opacity-80">{c.label}</span>
        </span>
      ))}
    </div>
  );
}

export default async function AdminUsersIndex() {
  const me = await getCurrentUser();
  const canAdd = STAFF_ADMIN_ROLES.includes(me.role);
  const canAssignSchools = ["ImpactAssessment", "Admin"].includes(me.role);
  const canSetPrimaryDistrict = STAFF_ADMIN_ROLES.includes(me.role);
  const canAssignTargets = ["CountryProgramLead", "CountryDirector", "HumanResource", "Admin"].includes(me.role);
  const fy = activeFinancialYear().id;
  const assignableSchools = intakeSchools.map((s) => ({
    schoolId: s.schoolId, schoolName: s.schoolName, district: s.district, assignedCceo: s.assignedCceo,
  }));
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
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <StaffHealthStrip />
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
            const tone = STATUS_TONE[r.status] ?? "amber";
            return (
              <div key={s.staffId} className="flex items-center gap-3 px-4 py-3.5">
                <span className="h-9 w-9 rounded-md grid place-items-center shrink-0 bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]">
                  <Users size={15} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Link href={`/admin/users/${encodeURIComponent(s.staffId)}`} className="text-body font-extrabold tracking-tight truncate hover:text-[var(--color-edify-primary)] hover:underline">{s.name}</Link>
                    <span className={cn(
                      "inline-flex px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0",
                      tone === "green" ? "bg-emerald-100 text-emerald-700" : tone === "slate" ? "bg-slate-100 text-slate-700" : "bg-amber-100 text-amber-700",
                    )}>{r.status.replace(/([A-Z])/g, " $1").trim()}</span>
                  </div>
                  <div className="text-caption muted truncate">
                    {s.email ?? ""} · {labelForRole(s.role)}{s.district ? ` · ${s.district}` : ""}
                    {r.requiredCount > 0 ? ` · Onboarding ${r.metCount}/${r.requiredCount}` : ""}
                    {nextGap ? ` · Next: ${nextGap}` : ""}
                  </div>
                </div>
                {canAssignSchools && s.role === "CCEO" && r.met.schools !== true && (
                  <AssignSchoolsControl staffId={s.staffId} staffName={s.name} schools={assignableSchools} />
                )}
                {canSetPrimaryDistrict && r.met.schools === true && r.met.primaryDistrict !== true && (
                  <PrimaryDistrictControl staffId={s.staffId} staffName={s.name} region={s.region} defaultDistrict={s.district} />
                )}
                {canAdd && (
                  <ChangeSupervisorControl staffId={s.staffId} staffName={s.name} role={s.role} currentSupervisorId={s.supervisorId} />
                )}
                {canAssignTargets && r.met.primaryDistrict === true && r.met.targetProfile !== true && (
                  <AssignTargetProfileControl
                    staffId={s.staffId}
                    staffName={s.name}
                    defaults={(() => { const d = defaultTargetProfileFor(s.staffId, s.role, fy); return { fy, visitTarget: d.visitTarget, trainingTarget: d.trainingTarget, ssaTarget: d.ssaTarget, clusterMeetingTarget: d.clusterMeetingTarget, partnerMonitoringTarget: d.partnerMonitoringTarget }; })()}
                  />
                )}
              </div>
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
