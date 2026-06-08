"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarRange, Check, Download, Filter, Shield } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { currentWeek } from "@/lib/funds/weekly-fund-mock";
import { cn } from "@/lib/utils";
import type { DisbursementFilter } from "./DisbursementQueue";

// Top header for the Field Fund Disbursement Command Center. The period chips
// reflect the active operating scope; the Filters popover + This-Week toggle
// genuinely filter the disbursement queue (state lives in the view), and
// Export Ledger downloads a real CSV.
export function AccountantDisbursementHeader({
  filter,
  onFilterChange,
  onExport,
}: {
  filter: DisbursementFilter;
  onFilterChange: (next: DisbursementFilter) => void;
  onExport: () => void;
}) {
  const statusActive = (filter.status ?? "all") !== "all";

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
          <Chip label={`Week ${currentWeek.weekOfMonth}`} tone="emerald" sub={`${currentWeek.daysRemaining}d left`} />

          <FiltersMenu filter={filter} onFilterChange={onFilterChange} active={statusActive} />

          <button
            type="button"
            onClick={() => onFilterChange({ ...filter, thisWeekOnly: !filter.thisWeekOnly })}
            aria-pressed={!!filter.thisWeekOnly}
            className={cn(
              "inline-flex items-center gap-1.5 h-9 px-3 rounded-xl border text-[12px] font-semibold",
              filter.thisWeekOnly
                ? "bg-emerald-600 border-transparent text-white"
                : "bg-white border-[var(--color-edify-border)] hover:bg-slate-50 text-slate-700",
            )}
          >
            <CalendarRange size={12} />
            <span className="hidden sm:inline">This Week</span>
          </button>

          <button
            type="button"
            onClick={onExport}
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

const STATUS_OPTIONS: { key: NonNullable<DisbursementFilter["status"]>; label: string }[] = [
  { key: "all", label: "All requests" },
  { key: "ready", label: "Ready to release" },
  { key: "blocked", label: "Blocked (gated)" },
];

function FiltersMenu({
  filter,
  onFilterChange,
  active,
}: {
  filter: DisbursementFilter;
  onFilterChange: (next: DisbursementFilter) => void;
  active: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          "inline-flex items-center gap-1.5 h-9 px-3 rounded-xl border text-[12px] font-semibold",
          active
            ? "bg-slate-900 border-transparent text-white"
            : "bg-white border-[var(--color-edify-border)] hover:bg-slate-50 text-slate-700",
        )}
      >
        <Filter size={12} />
        <span className="hidden sm:inline">Filters</span>
        {active && <span className="ml-0.5 inline-grid place-items-center min-w-4 h-4 px-1 rounded-full bg-white/20 text-[9px] font-bold">1</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-30 w-52 rounded-xl border border-[var(--color-edify-border)] bg-white shadow-[0_18px_40px_-18px_rgba(15,23,32,0.35)] p-1.5">
          <div className="px-2 py-1 text-[9.5px] font-bold uppercase tracking-wide muted">Release status</div>
          {STATUS_OPTIONS.map((o) => {
            const selected = (filter.status ?? "all") === o.key;
            return (
              <button
                key={o.key}
                type="button"
                onClick={() => { onFilterChange({ ...filter, status: o.key }); setOpen(false); }}
                className={cn(
                  "w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-[12px] font-semibold text-left",
                  selected ? "bg-[var(--color-edify-soft)]/60 text-slate-900" : "hover:bg-slate-50 text-slate-700",
                )}
              >
                {o.label}
                {selected && <Check size={13} className="text-emerald-600" />}
              </button>
            );
          })}
          {active && (
            <button
              type="button"
              onClick={() => { onFilterChange({ ...filter, status: "all" }); setOpen(false); }}
              className="w-full mt-1 px-2 py-1.5 rounded-lg text-[11px] font-bold text-rose-600 hover:bg-rose-50 text-left"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Chip({ label, sub, tone }: { label: string; sub?: string; tone?: "emerald" }) {
  const cls =
    tone === "emerald"
      ? "bg-emerald-100 text-emerald-700 border-emerald-200"
      : "bg-white text-slate-700 border-[var(--color-edify-border)]";
  return (
    <span className={`inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border text-[11.5px] font-extrabold ${cls}`}>
      {label}
      {sub && <span className="text-[10px] font-semibold opacity-80">· {sub}</span>}
    </span>
  );
}
