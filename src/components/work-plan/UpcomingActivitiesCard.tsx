"use client";

import Link from "next/link";
import { Clock, ChevronRight } from "lucide-react";
import { upcomingActivities } from "@/lib/work-plan-mock";

export function UpcomingActivitiesCard() {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[15px] font-extrabold tracking-tight">Upcoming Activities</h3>
        <Link href="/calendar" className="text-body font-semibold text-emerald-600">
          View Calendar
        </Link>
      </div>
      <div className="divide-y divide-[var(--color-edify-divider)]">
        {upcomingActivities.map((a) => (
          <Link
            key={a.id}
            href="/notifications"
            className="flex items-center gap-3 py-3 active:bg-[var(--color-edify-soft)]/40 -mx-1 px-1 rounded-md"
          >
            <div className="flex flex-col items-center w-12 shrink-0">
              <div className="text-[10px] font-extrabold tracking-wider text-emerald-600">{a.monthShort}</div>
              <div className="text-[22px] font-extrabold tabular leading-none">{a.day}</div>
            </div>
            <span className="self-stretch w-px bg-[#eef2f4]" />
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-bold leading-tight">{a.title}</div>
              <div className="text-[11.5px] muted leading-tight mt-0.5">{a.location}</div>
              <div className="inline-flex items-center gap-1 text-[11px] muted mt-1">
                <Clock size={10} />
                {a.time}
              </div>
            </div>
            <span className="shrink-0 inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-extrabold bg-emerald-50 text-emerald-700">
              {a.status}
            </span>
            <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        ))}
      </div>
    </section>
  );
}
