"use client";

// Create-from-school button — schedules a visit/training for THIS school into the
// user's My Plan (a Planned activity in the store). On success the page
// revalidates so the capacity bar bumps (and the school can gray out at quota).

import { useTransition, useState } from "react";
import { CalendarPlus, Check } from "lucide-react";
import { scheduleSchoolActivity } from "@/lib/actions/my-plan-actions";
import type { ActivityKind } from "@/lib/actions/store";

export function ScheduleActivityButton({
  schoolId, schoolName, kind, label, deliveryType = "staff", tone = "primary",
}: {
  schoolId: string;
  schoolName?: string;
  kind: ActivityKind;
  label: string;
  deliveryType?: "staff" | "partner";
  tone?: "primary" | "outline";
}) {
  const [pending, start] = useTransition();
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function onClick() {
    setErr(null);
    // Default to a date one week out; the row can be rescheduled from My Plan.
    const dateIso = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
    start(async () => {
      const r = await scheduleSchoolActivity({ schoolId, schoolName, kind, dateIso, deliveryType, partnerName: deliveryType === "partner" ? "Partner" : undefined });
      if (r.ok) setDone(true);
      else setErr(r.message ?? "Could not schedule.");
    });
  }

  if (err) return <span className="text-[11px] font-bold text-rose-600">{err}</span>;

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending || done}
      className={tone === "outline"
        ? "inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-primary)] text-[var(--color-edify-primary)] px-3 py-1.5 text-[11.5px] font-extrabold hover:bg-[var(--color-edify-soft)]/40 disabled:opacity-60"
        : "inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] text-white px-3 py-1.5 text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] disabled:opacity-60"}
    >
      {done ? <><Check size={13} /> Planned</> : <><CalendarPlus size={13} /> {pending ? "Planning…" : label}</>}
    </button>
  );
}
