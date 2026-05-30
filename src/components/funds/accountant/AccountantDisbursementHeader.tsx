"use client";

import { CalendarRange, Download, Filter, Shield } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { currentWeek } from "@/lib/funds/weekly-fund-mock";

// Top header for the Field Fund Disbursement Command Center. Now a
// thin adapter over <PageHeader> — the title row, breadcrumbs, search,
// bell, and avatar all flow through the canonical chrome. Period
// chips + Filters/This-Week/Export buttons ride the actions slot.
export function AccountantDisbursementHeader() {
  return (
    <PageHeader
      title="Field Fund Disbursement"
      subtitle="Money trail from country treasury → staff in the field. Releases only against Lead-approved weekly requests. Prior-week accountability gate enforced."
      titleBadge={
        <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-caption font-extrabold bg-emerald-100 text-emerald-700 border border-emerald-200">
          <Shield size={10} /> Controlled
        </span>
      }
      actions={
        <>
          <Chip label={currentWeek.fyLabel} />
          <Chip label={currentWeek.quarter} />
          <Chip label={currentWeek.monthLabel} />
          <Chip
            label={`Week ${currentWeek.weekOfMonth}`}
            tone="emerald"
            sub={`${currentWeek.daysRemaining}d left`}
          />
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
            Export Ledger
          </button>
        </>
      }
    />
  );
}

function Chip({
  label,
  sub,
  tone,
}: {
  label: string;
  sub?: string;
  tone?: "emerald";
}) {
  const cls =
    tone === "emerald"
      ? "bg-emerald-100 text-emerald-700 border-emerald-200"
      : "bg-white text-slate-700 border-[var(--color-edify-border)]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border text-[11.5px] font-extrabold ${cls}`}
    >
      {label}
      {sub && <span className="text-[10px] font-semibold opacity-80">· {sub}</span>}
    </span>
  );
}
