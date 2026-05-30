"use client";

import { ChevronDown, Search } from "lucide-react";
import { fundApprovalFilters } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";

// Filter bar — 4 stacked-label dropdowns + a search field.
//   • phone (<sm):    search lives on its own row at top; the 4
//                     dropdowns sit below as a horizontal-scroll strip
//                     so they don't eat 5×58px of vertical space.
//   • sm:             2-up grid for the dropdowns, search spans both.
//   • lg+:            single row of 5 (4 dropdowns + search).
export function FundApprovalsFilterBar() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      {/* Mobile search — own row */}
      <label className="card flex sm:hidden items-center gap-2 h-11 px-3 rounded-xl mb-2">
        <Search size={14} className="text-slate-400 shrink-0" />
        <input
          type="text"
          placeholder="Search CCEO or district…"
          className="bg-transparent outline-none flex-1 text-[12px] text-slate-700 placeholder:text-slate-400 min-w-0"
        />
      </label>

      {/* Mobile filter strip — horizontal scroll, fixed-width pills */}
      <div className="sm:hidden -mx-3 px-3 overflow-x-auto pb-1">
        <div className="inline-flex items-stretch gap-1.5 whitespace-nowrap">
          <Select compact label="Financial Year" value={fundApprovalFilters.financialYear} />
          <Select compact label="Month"          value={fundApprovalFilters.month} />
          <Select compact label="Region"         value={fundApprovalFilters.region} />
          <Select compact label="District"       value={fundApprovalFilters.district} />
        </div>
      </div>

      {/* sm+ grid — 2 cols at sm/md, 5 cols at lg+ */}
      <div className="hidden sm:grid grid-cols-2 lg:grid-cols-5 gap-2">
        <Select label="Financial Year" value={fundApprovalFilters.financialYear} />
        <Select label="Month"          value={fundApprovalFilters.month} />
        <Select label="Region"         value={fundApprovalFilters.region} />
        <Select label="District"       value={fundApprovalFilters.district} />

        <label className="card flex items-center gap-2 h-[58px] px-3 rounded-xl col-span-2 lg:col-span-1">
          <Search size={14} className="text-slate-400 shrink-0" />
          <input
            type="text"
            placeholder="Search CCEO or district…"
            className="bg-transparent outline-none flex-1 text-body text-slate-700 placeholder:text-slate-400 min-w-0"
          />
        </label>
      </div>
    </section>
  );
}

function Select({
  label,
  value,
  compact,
}: {
  label:   string;
  value:   string;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      className={cn(
        "card card-lift flex items-center justify-between gap-2 rounded-xl text-left cursor-default",
        compact
          ? "h-11 px-2.5 min-w-[150px] shrink-0"
          : "h-[58px] px-3",
      )}
    >
      <span className="flex flex-col items-start leading-tight min-w-0">
        <span className="text-[9.5px] muted font-bold uppercase tracking-wide">{label}</span>
        <span className={cn(
          "font-extrabold text-slate-900 truncate w-full num-hero",
          compact ? "text-[12px] mt-0" : "text-[13.5px] mt-0.5",
        )}>
          {value}
        </span>
      </span>
      <ChevronDown size={12} className="text-slate-400 shrink-0" />
    </button>
  );
}
