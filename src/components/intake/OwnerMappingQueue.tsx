"use client";

// IA owner-mapping queue — resolve uploaded schools whose Account Owner name
// doesn't match a registered staff member. IA maps the entered name to a real
// staff member; those schools then auto-distribute into the right portfolio.
//
// Flag-and-resolve, never delete: an unmatched owner is surfaced here instead of
// silently dropping the school or its ownership.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { UserCheck, AlertCircle } from "lucide-react";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { mapUnmatchedOwner } from "@/lib/actions/intake-actions";

export type UnmatchedOwnerLite = { name: string; count: number; schoolNames: string[] };
export type StaffOption = { staffId: string; name: string; role: string };

export function OwnerMappingQueue({ unmatched, staff }: { unmatched: UnmatchedOwnerLite[]; staff: StaffOption[] }) {
  if (unmatched.length === 0) {
    return (
      <section className="card p-3.5">
        <h2 className="text-[12.5px] font-extrabold tracking-tight">Owner-mapping queue</h2>
        <p className="text-[11.5px] muted mt-1">
          Every uploaded school resolves to a registered Account Owner. Nothing to map.
        </p>
      </section>
    );
  }

  return (
    <section className="card p-3.5">
      <div className="flex items-start gap-2 mb-2">
        <AlertCircle size={15} className="text-amber-600 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <h2 className="text-[12.5px] font-extrabold tracking-tight">Owner-mapping queue · {unmatched.length}</h2>
          <p className="text-[11px] muted">
            These schools were uploaded with an Account Owner that isn&apos;t a registered staff member. Map each
            entered name to the right person — the schools then appear in that person&apos;s portfolio automatically.
            Nothing is deleted.
          </p>
        </div>
      </div>
      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {unmatched.map((u) => (
          <OwnerRow key={u.name} unmatched={u} staff={staff} />
        ))}
      </ul>
    </section>
  );
}

function OwnerRow({ unmatched, staff }: { unmatched: UnmatchedOwnerLite; staff: StaffOption[] }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [staffId, setStaffId] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  function map() {
    if (!staffId) return;
    setMsg(null);
    start(async () => {
      const res = await mapUnmatchedOwner(unmatched.name, staffId);
      if (res.ok) {
        setMsg(`Mapped ${res.mapped} school${res.mapped === 1 ? "" : "s"} to ${res.staffName}.`);
        router.refresh();
      } else if (res.reason === "FORBIDDEN") {
        setMsg("You don't have permission to map owners.");
      } else if (res.reason === "NO_MATCH") {
        setMsg("Those schools were already mapped.");
      } else {
        setMsg("Pick a registered staff member.");
      }
    });
  }

  return (
    <li className="py-2.5">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="text-body font-extrabold tracking-tight truncate">
            &ldquo;{unmatched.name}&rdquo;
            <span className="ml-2 inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700">
              {unmatched.count} school{unmatched.count === 1 ? "" : "s"}
            </span>
          </div>
          <div className="text-caption muted truncate">{unmatched.schoolNames.join(" · ")}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Select aria-label="Map to staff" placeholder="Map to…" value={staffId} selectSize="sm" wrapperClassName="min-w-[190px]"
            options={staff.map((s) => ({ value: s.staffId, label: `${s.name} · ${s.role}` }))}
            onChange={(e) => setStaffId(e.target.value)} />
          <Button variant="primary" size="sm" Icon={UserCheck} onClick={map} disabled={pending || !staffId}>
            {pending ? "Mapping…" : "Map"}
          </Button>
        </div>
      </div>
      {msg && <p className="text-[11px] muted mt-1">{msg}</p>}
    </li>
  );
}
