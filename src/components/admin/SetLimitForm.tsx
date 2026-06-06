"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";
import { setStaffSupportLimit } from "@/lib/actions/capacity-actions";

// CD/IA inline control to set a staff member's direct-support limit.
export function SetLimitForm({ staffId, current }: { staffId: string; current: number }) {
  const [val, setVal] = useState(String(current));
  const [pending, start] = useTransition();
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState(false);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setErr(false);
        start(async () => {
          const r = await setStaffSupportLimit(staffId, Number(val));
          if (r.ok) { setSaved(true); setTimeout(() => setSaved(false), 1600); }
          else setErr(true);
        });
      }}
      className="inline-flex items-center gap-1.5"
    >
      <input
        type="number" min={0} max={9999} value={val}
        onChange={(e) => setVal(e.target.value)}
        className="w-16 rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px] tabular"
      />
      <button
        type="submit" disabled={pending}
        className="inline-flex items-center gap-1 rounded-md bg-[var(--color-edify-primary)] text-white px-2.5 py-1 text-[11px] font-extrabold disabled:opacity-50"
      >
        {saved ? <><Check size={11} /> Saved</> : pending ? "…" : "Set"}
      </button>
      {err && <span className="text-[10.5px] text-rose-600 font-bold">failed</span>}
    </form>
  );
}
