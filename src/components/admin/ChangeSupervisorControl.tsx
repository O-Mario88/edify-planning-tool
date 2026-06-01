"use client";

// Supervisor re-assignment — Phase 3. CD/HR/RVP/Admin reassign a staff member's
// supervisor (transfer, workload balancing, restructuring) with a required
// reason; the action audits old→new so the change history is reconstructable.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { UserCog, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { ORG_STAFF, supervisorRoleFor } from "@/lib/org/supervision";
import { labelForRole } from "@/lib/intake/staff-creation-core";
import { assignSupervisor } from "@/lib/actions/staff-actions";
import type { EdifyRole } from "@/lib/auth";

export function ChangeSupervisorControl({
  staffId,
  staffName,
  role,
  currentSupervisorId,
}: {
  staffId: string;
  staffName: string;
  role: EdifyRole;
  currentSupervisorId?: string | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [supervisorId, setSupervisorId] = useState(currentSupervisorId ?? "");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const needed = supervisorRoleFor(role);
  const options = useMemo(
    () => (needed ? ORG_STAFF.filter((s) => s.role === needed).map((s) => ({ value: s.staffId, label: `${s.name} (${labelForRole(s.role)})` })) : []),
    [needed],
  );

  function submit() {
    if (!supervisorId || reason.trim().length < 4) { setMsg("Pick a supervisor and give a reason (4+ chars)."); return; }
    setMsg(null);
    start(async () => {
      const res = await assignSupervisor({ staffId, newSupervisorId: supervisorId, reason: reason.trim() });
      if (res.ok) {
        setMsg("Supervisor reassigned — logged to the audit trail.");
        router.refresh();
        setTimeout(() => setOpen(false), 1100);
      } else {
        setMsg(
          res.reason === "FORBIDDEN" ? "Only CD / HR / RVP / Admin can reassign."
          : res.reason === "WRONG_LEVEL" ? `Supervisor must be a ${needed ? labelForRole(needed) : "valid role"}.`
          : `Could not reassign (${res.reason}).`,
        );
      }
    });
  }

  if (!needed) return null; // top-of-chain roles have no supervisor

  return (
    <>
      <Button variant="ghost" size="sm" Icon={UserCog} onClick={() => setOpen(true)}>
        Change supervisor
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Change supervisor — ${staffName}`}
        description={`A ${labelForRole(role)} reports to a ${labelForRole(needed)}. The change is audited (old → new + reason).`}
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending} Icon={CheckCircle2}>
                {pending ? "Saving…" : "Reassign"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-3">
          <Select label="New supervisor" placeholder="Select supervisor" value={supervisorId} options={options}
            onChange={(e) => setSupervisorId(e.target.value)} />
          <Input label="Reason" placeholder="Workload balancing / transfer / restructuring…" value={reason}
            onChange={(e) => setReason(e.target.value)} />
        </div>
      </Modal>
    </>
  );
}
