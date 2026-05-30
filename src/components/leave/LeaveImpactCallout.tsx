"use client";

import Link from "next/link";
import { CalendarRange, ArrowRight } from "lucide-react";
import {
  leaveSummaryForCpl,
  leaveSummaryForCceo,
} from "@/lib/leave-mock";

// Reusable callout that surfaces the planning engine's leave/holiday impact
// inside other dashboards (CCEO, Country Program Lead). Same data source as
// the Leave & Holiday Planning Dashboard — never reach into raw arrays.
export function LeaveImpactCallout({
  variant,
  staffId,
}: {
  variant: "cpl" | "cceo";
  staffId?: string;
}) {
  if (variant === "cceo") {
    const s = leaveSummaryForCceo(staffId ?? "STF-SK-001");
    return (
      <Wrapper>
        <Row label="Upcoming leave (you)" value={s.upcomingCount} />
        <Row label="Activities blocked by leave" value={s.blockedActivityCount} />
        <Row label="Next leave starts" value={s.nextLeaveStart ?? "—"} />
      </Wrapper>
    );
  }

  const s = leaveSummaryForCpl();
  return (
    <Wrapper>
      <Row label="Staff on leave this month" value={s.onLeaveThisMonth} />
      <Row label="Blocked planning days" value={s.blockedDays} />
      <Row label="Auto-blocked conflicts" value={s.conflictsInQueue} />
      <Row label="Conference week" value={s.conferenceWeek} />
    </Wrapper>
  );
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
          <CalendarRange size={14} />
        </span>
        <h3 className="text-[13px] font-bold">Leave & Holiday Impact</h3>
        <Link
          href="/leave"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Open Planning Engine
          <ArrowRight size={11} />
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">{children}</div>
      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-caption muted">
        Sundays, public holidays, conference weeks, and approved leave are blocked across the planning tool.
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="muted">{label}</span>
      <span className="font-extrabold tabular text-[var(--color-edify-text)]">{value}</span>
    </div>
  );
}
