"use client";

import { CalendarRange, ChevronDown, Filter, Globe2, GitCompareArrows, Search } from "lucide-react";
import { countryFundFilters } from "@/lib/country-fund-approvals-mock";
import { cn } from "@/lib/utils";

// CD filter bar — 3 stacked-label dropdowns (FY · Month · Country/Region)
// + a search field + Filters button on the right. Different shape from
// the PL bar because the CD operates at the country level (not by
// region/district).
export function CountryFundFilterBar() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      {/* Mobile: search on top, filters as a horizontal scroll strip */}
      <label className="card flex sm:hidden items-center gap-2 h-11 px-3 rounded-xl mb-2">
        <Search size={14} className="text-slate-400 shrink-0" />
        <input
          type="text"
          placeholder="Search leads, regions or requests…"
          className="bg-transparent outline-none flex-1 text-[12px] text-slate-700 placeholder:text-slate-400 min-w-0"
        />
      </label>
      <div className="sm:hidden -mx-3 px-3 overflow-x-auto pb-1">
        <div className="inline-flex items-stretch gap-1.5 whitespace-nowrap">
          <SelectPill compact label="Financial Year" value={countryFundFilters.financialYear} />
          <SelectPill compact label="Month"          value={countryFundFilters.month} />
          <SelectPill compact label="Country / Region" value={countryFundFilters.country} />
        </div>
      </div>

      {/* sm+ — 3 dropdowns + search + Filters button on one row at lg+ */}
      <div className="hidden sm:flex items-stretch gap-2 flex-wrap">
        <SelectPill icon={CalendarRange}    label="Financial Year"   value={countryFundFilters.financialYear} />
        <SelectPill icon={GitCompareArrows} label="Month"            value={countryFundFilters.month} />
        <SelectPill icon={Globe2}           label="Country / Region" value={countryFundFilters.country} />

        <label className="card flex items-center gap-2 h-[58px] px-3 rounded-xl flex-1 min-w-[200px]">
          <Search size={14} className="text-slate-400 shrink-0" />
          <input
            type="text"
            placeholder="Search leads, regions or requests…"
            className="bg-transparent outline-none flex-1 text-body text-slate-700 placeholder:text-slate-400 min-w-0"
          />
        </label>

        <button
          type="button"
          className="inline-flex items-center justify-center gap-1.5 h-[58px] px-4 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
        >
          <Filter size={13} />
          Filters
        </button>
      </div>
    </section>
  );
}

function SelectPill({
  label,
  value,
  compact,
  icon: Icon,
}: {
  label: string;
  value: string;
  compact?: boolean;
  icon?: typeof Search;
}) {
  return (
    <button
      type="button"
      className={cn(
        "card card-lift flex items-center justify-between gap-2 rounded-xl text-left cursor-default",
        compact ? "h-11 px-2.5 min-w-[150px] shrink-0" : "h-[58px] px-3 min-w-[180px]",
      )}
    >
      <span className="flex items-center gap-2 min-w-0 flex-1">
        {Icon && !compact && <Icon size={14} className="text-slate-400 shrink-0" />}
        <span className="flex flex-col items-start leading-tight min-w-0">
          <span className="text-[9.5px] muted font-bold uppercase tracking-wide">{label}</span>
          <span className={cn(
            "font-extrabold text-slate-900 truncate w-full num-hero",
            compact ? "text-[12px] mt-0" : "text-[13.5px] mt-0.5",
          )}>
            {value}
          </span>
        </span>
      </span>
      <ChevronDown size={12} className="text-slate-400 shrink-0" />
    </button>
  );
}
