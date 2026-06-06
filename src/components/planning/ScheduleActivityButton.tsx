"use client";

// Create-from-school button — schedules a visit/training for THIS school into the
// user's My Plan (a Planned activity in the store). On success the page
// revalidates so the capacity bar bumps (and the school can gray out at quota).

import { useTransition, useState } from "react";
import { CalendarPlus, Check } from "lucide-react";
import { scheduleSchoolActivity } from "@/lib/actions/my-plan-actions";
import type { ActivityKind } from "@/lib/actions/store";

export function ScheduleActivityButton({
  schoolId, schoolName, kind, label,
}: {
  schoolId: string;
  schoolName?: string;
  kind: ActivityKind;
  label: string;
}) {
  const [pending, start] = useTransition();
  const [done, setDone] = useState(false);

  function onClick() {
    // Default to a date one week out; the row can be rescheduled from My Plan.
    const dateIso = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
    start(async () => {
      const r = await scheduleSchoolActivity({ schoolId, schoolName, kind, dateIso });
      if (r.ok) setDone(true);
    });
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending || done}
      className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] text-white px-3 py-1.5 text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] disabled:opacity-60"
    >
      {done ? <><Check size={13} /> Planned</> : <><CalendarPlus size={13} /> {pending ? "Planning…" : label}</>}
    </button>
  );
}
