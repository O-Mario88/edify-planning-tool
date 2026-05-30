"use client";

import {
  Building2,
  CalendarRange,
  ChevronDown,
  Download,
  Filter,
  GitCompareArrows,
  type LucideIcon,
} from "lucide-react";
import { teamTargetsBillionHeader } from "@/lib/team-targets-billion-mock";
import { cn } from "@/lib/utils";

// Slim Operating-View header for the team-targets dashboard.
// Same structure as MyTargetsTopBar but with team-shaped copy:
// eyebrow says "Team Targets · May 2026", the role context line
// reads "144 staff supervised · Week 2 of 4". Filters surface
// region + quarter + month + financial year so a Program Lead can
// scope the view without leaving the page.
export function TeamTargetsTopBar({ firstName }: { firstName?: string }) {
  const h = teamTargetsBillionHeader;
  const name = firstName ?? h.firstName;
  return (
    <header className="pl-4 sm:pl-16 md:pl-6 pr-4 lg:pr-6 pt-5 pb-3">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-caption uppercase tracking-[0.14em] text-slate-400 font-bold">
            {h.eyebrow}
          </div>
          <h1 className="text-[22px] sm:text-[24px] lg:text-[26px] font-extrabold tracking-tight text-slate-900 mt-0.5">
            {h.greeting}, <span className="text-slate-900">{name}.</span>
          </h1>
          <p className="text-[11.5px] muted mt-0.5">
            {h.dateLong} · Week {h.weekNo} of {h.weekTotal} · {h.staffCount} staff supervised
          </p>
        </div>

        <div className="ml-auto hidden md:flex items-start gap-1.5 flex-wrap justify-end">
          <FilterPill icon={CalendarRange}    label="Financial Year" value={h.filters.financialYear} />
          <FilterPill icon={GitCompareArrows} label="Quarter"        value={h.filters.quarter} />
          <FilterPill icon={Filter}           label="Month"          value={h.filters.month} />
          <FilterPill icon={Building2}        label="Region"         value={h.filters.region} />

          <span aria-hidden className="h-9 w-px bg-[var(--color-edify-border)] mx-1 self-center" />

          <button
            type="button"
            className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold inline-flex items-center gap-1.5 text-slate-700 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
          >
            <Download size={12} className="text-[var(--color-edify-muted)]" />
            Export Report
          </button>
        </div>
      </div>

      {/* Mobile filter rail */}
      <div className="md:hidden mt-3 -mx-4 px-4 overflow-x-auto scrollbar">
        <div className="flex items-start gap-1.5 w-max pb-1">
          <FilterPill icon={CalendarRange}    label="Financial Year" value={h.filters.financialYear} />
          <FilterPill icon={GitCompareArrows} label="Quarter"        value={h.filters.quarter} />
          <FilterPill icon={Filter}           label="Month"          value={h.filters.month} />
          <FilterPill icon={Building2}        label="Region"         value={h.filters.region} />
        </div>
      </div>
    </header>
  );
}

function FilterPill({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <button
      type="button"
      className={cn(
        "h-9 px-2.5 rounded-xl text-[12px] font-semibold inline-flex items-center gap-1.5 transition-colors",
        "bg-[var(--color-edify-soft)]/50 hover:bg-[var(--color-edify-soft)] text-slate-700",
        "border border-transparent hover:border-[var(--color-edify-border)]",
      )}
    >
      <Icon size={12} className="text-[var(--color-edify-muted)]" />
      <span className="flex flex-col items-start leading-tight">
        <span className="text-[9px] uppercase tracking-wide muted font-bold">{label}</span>
        <span className="text-slate-900">{value}</span>
      </span>
      <ChevronDown size={11} className="text-[var(--color-edify-muted)] ml-1" />
    </button>
  );
}
