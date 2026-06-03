"use client";

// Accountant — staff (Edify-managed) cluster activities that are IA-confirmed
// and awaiting Netsuite accountability. The accountant records the Netsuite
// Expense ID to close it (only available because IA already confirmed).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CalendarDays, Check, ShieldCheck, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { recordStaffAccountabilityAction } from "@/lib/actions/cluster-actions";

export type StaffAccountabilityVM = {
  id: string;
  clusterName: string;
  district: string;
  label: string;
  date: string;
  salesforceTrainingId?: string;
  total: number;
  responsible?: string;
  iaConfirmedAt?: string;
};

export function StaffClusterAccountabilityQueue({ items }: { items: StaffAccountabilityVM[] }) {
  if (items.length === 0) {
    return <p className="muted text-[12.5px]">No staff cluster activities awaiting Netsuite accountability.</p>;
  }
  return (
    <ul className="divide-y divide-[var(--color-edify-divider)]">
      {items.map((it) => <Row key={it.id} it={it} />)}
    </ul>
  );
}

function Row({ it }: { it: StaffAccountabilityVM }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [netsuite, setNetsuite] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    if (!netsuite.trim()) { setError("Enter the Netsuite Expense ID."); return; }
    start(async () => {
      const res = await recordStaffAccountabilityAction(it.id, netsuite.trim());
      if (!res.ok) { setError(res.reason === "FORBIDDEN" ? "Not permitted for your role." : (res.reason === "FAILED" ? res.message ?? "Failed." : "Failed.")); return; }
      router.refresh();
    });
  }

  return (
    <li className="py-3">
      <div className="flex items-center gap-2 flex-wrap">
        <CalendarDays size={13} className="text-[var(--color-edify-primary)] shrink-0" />
        <span className="text-[12.5px] font-extrabold">{it.label}</span>
        <span className="text-[11.5px] muted">{it.clusterName} · {it.district} · {it.date}</span>
        {it.salesforceTrainingId && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-slate-100 text-slate-600">{it.salesforceTrainingId}</span>}
        <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 inline-flex items-center gap-1"><ShieldCheck size={9} /> IA confirmed{it.iaConfirmedAt ? ` · ${it.iaConfirmedAt.slice(0, 10)}` : ""}</span>
      </div>
      <p className="text-[11px] muted mt-0.5">{it.total} participants{it.responsible ? ` · ${it.responsible}` : ""}</p>
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <input value={netsuite} onChange={(e) => setNetsuite(e.target.value)} placeholder="Netsuite Expense ID" className="h-8 px-2 w-48 rounded-md border border-[var(--color-edify-border)] bg-[var(--surface-1,#fff)] text-[11.5px]" />
        <button type="button" disabled={pending || !netsuite.trim()} onClick={submit}
          className={cn("inline-flex items-center gap-1 h-8 px-2.5 rounded-md text-[11.5px] font-semibold text-white", pending || !netsuite.trim() ? "bg-slate-300" : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]")}>
          <Check size={12} /> Record accountability
        </button>
        {error && <span className="text-[10.5px] text-rose-600 inline-flex items-center gap-1"><AlertTriangle size={10} /> {error}</span>}
      </div>
    </li>
  );
}
