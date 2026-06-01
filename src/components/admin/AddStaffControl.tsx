"use client";

// Add Staff — CD/HR onboarding entrypoint on /admin/users.
//
// Phase 1 of the Staff Onboarding & Activation workflow: create the record
// (account + role + supervisor). The drawer mirrors the data-intake NewSchool
// drawer — geography cascade + inline validation — and the supervisor selector
// is driven by the reporting chain (a CCEO's supervisor must be a Program Lead,
// etc.). Creation leaves the staff in a Pending* state; IA assigns schools next.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { UserPlus } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { REGIONS, districtsInRegion, type UgandaRegion } from "@/lib/geography";
import { ORG_STAFF, orgStaff, supervisorRoleFor } from "@/lib/org/supervision";
import {
  CREATABLE_STAFF_ROLES,
  labelForRole,
  validateNewStaff,
  type NewStaffInput,
} from "@/lib/intake/staff-creation-core";
import { createStaff } from "@/lib/actions/staff-actions";
import type { EdifyRole } from "@/lib/auth";

const EMPTY = {
  name: "", email: "", role: "" as EdifyRole | "", region: "", district: "",
  jobTitle: "", supervisorStaffId: "",
};

export function AddStaffControl({ existingEmails }: { existingEmails: string[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [form, setForm] = useState<typeof EMPTY>({ ...EMPTY });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const emailSet = useMemo(() => new Set(existingEmails.map((e) => e.toLowerCase())), [existingEmails]);

  const districtOptions = useMemo(
    () => (form.region ? districtsInRegion(form.region as UgandaRegion).map((d) => ({ value: d, label: d })) : []),
    [form.region],
  );
  // A staff member's supervisor must hold the role one step up the chain.
  const supervisorOptions = useMemo(() => {
    if (!form.role) return [];
    const needed = supervisorRoleFor(form.role as EdifyRole);
    if (!needed) return [];
    return ORG_STAFF.filter((s) => s.role === needed).map((s) => ({ value: s.staffId, label: `${s.name} (${labelForRole(s.role)})` }));
  }, [form.role]);

  const needsSupervisor = form.role ? !!supervisorRoleFor(form.role as EdifyRole) : false;

  function set<K extends keyof typeof form>(k: K, v: (typeof form)[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function submit() {
    setMsg(null);
    const input: NewStaffInput = { ...form, role: form.role };
    const v = validateNewStaff(input, emailSet, (id) => orgStaff(id)?.role);
    if (!v.ok) { setErrors(v.errors); return; }
    setErrors({});
    start(async () => {
      const res = await createStaff(input);
      if (res.ok) {
        setMsg(`${form.name} added — status ${res.status.replace(/([A-Z])/g, " $1").trim()}. IA notified to assign schools.`);
        setForm({ ...EMPTY });
        router.refresh();
        setTimeout(() => setOpen(false), 1100);
      } else if (res.reason === "INVALID_INPUT") {
        setErrors(res.errors);
      } else {
        setMsg("You don't have permission to add staff (CD / HR only).");
      }
    });
  }

  return (
    <>
      <Button variant="primary" size="sm" Icon={UserPlus} onClick={() => setOpen(true)}>
        Add staff
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add a staff member"
        description="Create the account + role + supervisor. The staff member stays in onboarding until IA assigns schools, a primary district is set, and targets are assigned."
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending} Icon={UserPlus}>
                {pending ? "Adding…" : "Add staff"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Input label="Full name" placeholder="Joyce Akinyi" value={form.name} error={errors.name}
            onChange={(e) => set("name", e.target.value)} />
          <Input label="Registered email" type="email" placeholder="joyce.akinyi@edify.org" value={form.email}
            error={errors.email} onChange={(e) => set("email", e.target.value)} />
          <Select label="Role" placeholder="Select role" value={form.role} error={errors.role}
            options={CREATABLE_STAFF_ROLES.map((r) => ({ value: r, label: labelForRole(r) }))}
            onChange={(e) => { set("role", e.target.value as EdifyRole); set("supervisorStaffId", ""); }} />
          <Input label="Job title (optional)" placeholder="Field Officer" value={form.jobTitle}
            onChange={(e) => set("jobTitle", e.target.value)} />
          <Select label="Region" placeholder="Select region" value={form.region} error={errors.region}
            options={REGIONS.map((r) => ({ value: r.key, label: r.label }))}
            onChange={(e) => { set("region", e.target.value); set("district", ""); }} />
          <Select label="District" placeholder={form.region ? "Select district" : "Pick a region first"} value={form.district}
            error={errors.district} disabled={!form.region} options={districtOptions}
            onChange={(e) => set("district", e.target.value)} />
          {needsSupervisor && (
            <Select label="Supervisor" placeholder="Select supervisor" value={form.supervisorStaffId}
              error={errors.supervisorStaffId} options={supervisorOptions}
              helper={form.role ? `A ${labelForRole(form.role as EdifyRole)} reports to a ${labelForRole(supervisorRoleFor(form.role as EdifyRole)!)}.` : undefined}
              onChange={(e) => set("supervisorStaffId", e.target.value)} />
          )}
        </div>
      </Modal>
    </>
  );
}
