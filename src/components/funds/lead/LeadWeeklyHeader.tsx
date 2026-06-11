"use client";

import { PageHeader } from "@/components/ui/PageHeader";
import { currentWeek } from "@/lib/funds/weekly-fund-mock";

// Header for the Program Lead Weekly Fund Approval Queue. Thin adapter
// over <PageHeader>. The old Filters / This Week / Export buttons were
// dead stubs (no handlers, no system behind them) and were removed; the
// FY + week pills stay as live context. Search falls back to the global
// ⌘K palette.
export function LeadWeeklyHeader() {
  return (
    <PageHeader
      title="Weekly Fund Approvals"
      subtitle="Review each staff's auto-generated weekly fund request. Approve to release disbursement, or return with notes when the plan needs adjusting."
      actions={
        <>
          <span className="inline-flex items-center gap-1 h-9 px-2.5 rounded-xl border border-[var(--color-edify-border)] bg-white text-[11.5px] font-extrabold text-slate-700">
            {currentWeek.fyLabel}
          </span>
          <span className="inline-flex items-center gap-1 h-9 px-2.5 rounded-xl border border-emerald-200 bg-emerald-50 text-[11.5px] font-extrabold text-emerald-700">
            Week {currentWeek.weekOfMonth} · {currentWeek.daysRemaining}d left
          </span>
        </>
      }
    />
  );
}
