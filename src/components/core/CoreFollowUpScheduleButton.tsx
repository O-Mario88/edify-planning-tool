"use client";

// Schedule (or assign to a partner) the Follow-Up SSA once a core package is
// complete. Staff/CCEO/PL action — IA still records the actual scores after.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { scheduleCoreFollowUpSsa } from "@/lib/actions/core-actions";
import { listPartners } from "@/lib/partners-store";

const MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"];

export function CoreFollowUpScheduleButton({ planId }: { planId: string }) {
  const [open, setOpen] = useState(false);
  const [assignee, setAssignee] = useState<"myself" | "partner">("myself");
  const [partnerName, setPartnerName] = useState("");
  const [month, setMonth] = useState("Jun");
  const [week, setWeek] = useState("1");
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md border border-[var(--color-edify-border)] text-[11px] font-bold hover:bg-[var(--color-edify-soft)]/40">
        <CalendarClock size={12} /> Schedule Follow-Up SSA
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap">
      <select value={assignee} onChange={(e) => setAssignee(e.target.value as "myself" | "partner")} aria-label="Assignee" className="h-7 rounded-md border border-[var(--color-edify-border)] text-[11px] px-1">
        <option value="myself">Myself</option>
        <option value="partner">Partner</option>
      </select>
      {assignee === "partner" && (
        <>
          <input value={partnerName} onChange={(e) => setPartnerName(e.target.value)} list="core-fu-partner-list" placeholder="Partner org" aria-label="Partner"
            className="h-7 w-[130px] rounded-md border border-[var(--color-edify-border)] text-[11px] px-2" />
          <datalist id="core-fu-partner-list">{listPartners().map((p) => <option key={p.id} value={p.name} />)}</datalist>
        </>
      )}
      <select value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" className="h-7 rounded-md border border-[var(--color-edify-border)] text-[11px] px-1">
        {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <select value={week} onChange={(e) => setWeek(e.target.value)} aria-label="Week" className="h-7 rounded-md border border-[var(--color-edify-border)] text-[11px] px-1">
        {[1, 2, 3, 4].map((w) => <option key={w} value={w}>Wk {w}</option>)}
      </select>
      <button type="button" disabled={isPending || (assignee === "partner" && partnerName.trim().length < 2)}
        onClick={() => start(async () => {
          const res = await scheduleCoreFollowUpSsa(planId, { assignee, partnerName: partnerName.trim() || undefined, monthLabel: `${month} 2026`, week: Number(week) });
          if (res.ok) { pushToast({ tone: "success", title: "Follow-Up SSA scheduled", body: "IA will record the scores." }); setOpen(false); router.refresh(); }
          else pushToast({ tone: "warning", title: "Couldn't schedule", body: res.reason === "FORBIDDEN" ? "Not your role." : "Try again." });
        })}
        className="h-7 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold disabled:opacity-50">
        {isPending ? <Loader2 size={11} className="animate-spin" /> : "Schedule"}
      </button>
      <button type="button" onClick={() => setOpen(false)} aria-label="Cancel" className="w-6 h-7 grid place-items-center text-slate-500"><X size={12} /></button>
    </span>
  );
}
