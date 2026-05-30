"use client";

import { CalendarRange, Download, Filter } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { currentWeek } from "@/lib/funds/weekly-fund-mock";

// Header for the Program Lead Weekly Fund Approval Queue. Now a thin
// adapter over <PageHeader>; the page's own chrome (search, bell,
// avatar, breadcrumbs) comes from the canonical primitive.
export function LeadWeeklyHeader() {
  return (
    <PageHeader
      title="Weekly Fund Approvals"
      subtitle="Review each staff's auto-generated weekly fund request. Approve to release disbursement, or return with notes when the plan needs adjusting."
      searchPlaceholder="Search staff…"
      actions={
        <>
          <span className="inline-flex items-center gap-1 h-9 px-2.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-[11.5px] font-extrabold text-slate-700">
            {currentWeek.fyLabel}
          </span>
          <span className="inline-flex items-center gap-1 h-9 px-2.5 rounded-xl border border-emerald-200 bg-emerald-50 text-[11.5px] font-extrabold text-emerald-700">
            Week {currentWeek.weekOfMonth} · {currentWeek.daysRemaining}d left
          </span>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
          >
            <Filter size={12} />
            <span className="hidden sm:inline">Filters</span>
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[12px] font-semibold text-slate-700"
          >
            <CalendarRange size={12} />
            <span className="hidden sm:inline">This Week</span>
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
          >
            <Download size={12} />
            Export
          </button>
        </>
      }
    />
  );
}
