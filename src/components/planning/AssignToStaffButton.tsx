"use client";

// PL → supervised CCEO assignment. Creates the activity owned by the CCEO
// (respecting THEIR capacity) and notifies them. Server-side enforced.

import { useTransition, useState } from "react";
import { UserCheck, Check } from "lucide-react";
import { assignActivityToStaff } from "@/lib/actions/my-plan-actions";
import type { ActivityKind } from "@/lib/actions/store";

export function AssignToStaffButton({
  schoolId, schoolName, kind, targetStaffId, targetName,
}: {
  schoolId: string;
  schoolName?: string;
  kind: ActivityKind;
  targetStaffId: string;
  targetName: string;
}) {
  const [pending, start] = useTransition();
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function onClick() {
    setErr(null);
    const dateIso = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
    start(async () => {
      const r = await assignActivityToStaff({ schoolId, schoolName, kind, dateIso, targetStaffId });
      if (r.ok) setDone(true);
      else setErr(r.message ?? "Could not assign.");
    });
  }

  if (err) return <span className="text-[11px] text-rose-600 font-bold max-w-[260px]">{err}</span>;

  return (
    <button
      type="button" onClick={onClick} disabled={pending || done}
      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-border)] text-[var(--color-edify-text)] px-3 py-1.5 text-[11.5px] font-bold hover:bg-[var(--color-edify-soft)]/40 disabled:opacity-50"
    >
      {done ? <><Check size={13} /> Assigned to {targetName}</> : <><UserCheck size={13} /> {pending ? "Assigning…" : `Assign to ${targetName}`}</>}
    </button>
  );
}
