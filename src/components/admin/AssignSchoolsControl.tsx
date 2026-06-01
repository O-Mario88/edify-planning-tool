"use client";

// IA school assignment — assign onboarded schools to a staff member.
//
// Phase 4 of onboarding: this clears the "schools" activation gate. When IA
// assigns schools to a new CCEO, the schools enter the CCEO's portfolio +
// planning scope and the activation engine advances their status.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { School, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { assignSchoolsToStaff } from "@/lib/actions/intake-actions";

export type AssignableSchool = {
  schoolId: string;
  schoolName: string;
  district: string;
  assignedCceo?: string;
};

export function AssignSchoolsControl({
  staffId,
  staffName,
  schools,
}: {
  staffId: string;
  staffName: string;
  schools: AssignableSchool[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<string | null>(null);

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const count = picked.size;
  const ownsAlready = useMemo(
    () => new Set(schools.filter((s) => (s.assignedCceo ?? "").toLowerCase() === staffName.toLowerCase()).map((s) => s.schoolId)),
    [schools, staffName],
  );

  function submit() {
    if (count === 0) return;
    setMsg(null);
    start(async () => {
      const res = await assignSchoolsToStaff(staffId, [...picked]);
      if (res.ok) {
        setMsg(`Assigned ${res.assigned} school(s) to ${res.staffName}. Onboarding advances.`);
        setPicked(new Set());
        router.refresh();
        setTimeout(() => setOpen(false), 1100);
      } else {
        setMsg(res.reason === "FORBIDDEN" ? "Only IA / Admin can assign schools." : `Could not assign (${res.reason}).`);
      }
    });
  }

  return (
    <>
      <Button variant="secondary" size="sm" Icon={School} onClick={() => setOpen(true)}>
        Assign schools
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Assign schools to ${staffName}`}
        description="Pick onboarded schools to put in this staff member's portfolio. This clears their school-assignment onboarding gate."
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending || count === 0} Icon={CheckCircle2}>
                {pending ? "Assigning…" : `Assign ${count} school${count === 1 ? "" : "s"}`}
              </Button>
            </div>
          </div>
        }
      >
        {schools.length === 0 ? (
          <p className="text-[12px] muted">No onboarded schools yet. Add schools via Data Intake first.</p>
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => {
              const owned = ownsAlready.has(s.schoolId);
              const checked = picked.has(s.schoolId) || owned;
              return (
                <li key={s.schoolId}>
                  <button
                    type="button"
                    disabled={owned}
                    onClick={() => toggle(s.schoolId)}
                    className={cn(
                      "w-full flex items-center gap-3 py-2.5 text-left disabled:opacity-60",
                      !owned && "hover:bg-[var(--color-edify-soft)]/30",
                    )}
                  >
                    <span className={cn(
                      "h-5 w-5 rounded-md grid place-items-center shrink-0 border",
                      checked ? "bg-emerald-500 border-emerald-500 text-white" : "border-[var(--color-edify-border)] bg-white",
                    )}>
                      {checked && <CheckCircle2 size={13} />}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-[12.5px] font-extrabold tracking-tight truncate">{s.schoolName}</div>
                      <div className="text-[10.5px] muted truncate">
                        {s.schoolId} · {s.district}
                        {s.assignedCceo ? ` · currently: ${s.assignedCceo}` : " · unassigned"}
                      </div>
                    </div>
                    {owned && <span className="text-[10px] font-extrabold text-emerald-700 shrink-0">owned</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Modal>
    </>
  );
}
