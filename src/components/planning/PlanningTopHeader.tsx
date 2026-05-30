"use client";

import { Calendar, ChevronDown, MapPin, User, HelpCircle } from "lucide-react";
import { EntityHeader } from "@/components/ui/EntityHeader";
import { planningHeader, planningUser, planningFooter } from "@/lib/planning-mock";

export function PlanningTopHeader() {
  return (
    <EntityHeader
      title={planningHeader.title}
      subtitle={planningHeader.subtitle}
      statusBadge={<PlanningHeaderBadges />}
      filters={
        <>
          <LabeledPill label="Financial Year"  value={planningHeader.filters.financialYear} Icon={Calendar} />
          <LabeledPill label="Month"           value={planningHeader.filters.month}         Icon={Calendar} />
          <LabeledPill label="Region / Country" value={planningHeader.filters.region}       Icon={MapPin} />
          <LabeledPill label="Staff / CCEO"    value={planningHeader.filters.staff}         Icon={User} />
        </>
      }
      search={{ placeholder: planningHeader.searchPlaceholder }}
      messages={{ count: 3 }}
      notifications={{ count: 12 }}
      profile={{ name: planningUser.name, initials: planningUser.initials }}
    />
  );
}

// Snapshot + help affordance replacing the bottom banner & footer.
// Sits in the EntityHeader's `statusBadge` slot — same row as the
// page title, so the data-freshness context is one glance away
// instead of a full-width card at the bottom.
//
// Reads the timestamp from `planningFooter.asOf` so the badge and the
// footer never drift. The earlier copy ("Live · updated just now")
// was a lie — the schedule data refreshes on a fixed cadence, not in
// real-time, and the hardcoded "just now" eroded trust in every other
// number on the page.
function PlanningHeaderBadges() {
  // "Data as of 15 May 2025, 08:30 AM" → "15 May 2025 · 08:30 AM"
  const snapshotTime = planningFooter.asOf.replace(/^Data as of /, "").replace(",", " ·");
  return (
    <div className="inline-flex items-center gap-1.5">
      {/* Snapshot pulse — honest about cadence. */}
      <span className="inline-flex items-center gap-1.5 px-2 h-6 rounded-md bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
        <span className="relative grid place-items-center">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <span className="absolute h-1.5 w-1.5 rounded-full bg-emerald-500 animate-ping opacity-60" />
        </span>
        <span className="text-[10px] font-extrabold uppercase tracking-wider">Snapshot</span>
        <span className="text-[10px] muted font-semibold normal-case">· {snapshotTime}</span>
      </span>

      {/* Help — hover tooltip explains what this page does + does not do */}
      <span className="relative group">
        <button
          type="button"
          aria-label="About this page"
          className="h-6 w-6 grid place-items-center rounded-md hover:bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] transition-colors"
        >
          <HelpCircle size={13} />
        </button>
        <div
          role="tooltip"
          className="invisible opacity-0 group-hover:visible group-hover:opacity-100 transition-opacity absolute top-full mt-1.5 right-0 z-30 w-72 rounded-xl bg-white shadow-xl ring-1 ring-[var(--color-edify-divider)] p-3 text-left"
        >
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--color-edify-muted)]">
            About the Planning Console
          </div>
          <p className="text-[12px] text-[var(--color-edify-text)] leading-snug mt-1">
            Schedule visits and trainings only. <span className="font-extrabold">Clustering</span> by region,
            district, and shipping address is done in the School Directory — this page only appends dates,
            weeks, or months to those clusters.
          </p>
        </div>
      </span>
    </div>
  );
}

function LabeledPill({
  label,
  value,
  Icon,
}: {
  label: string;
  value: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}) {
  return (
    <button className="h-10 pl-3 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center gap-2 text-[13px] min-w-[150px]">
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="leading-tight text-left flex-1">
        <span className="block text-[10px] text-[var(--color-edify-muted)] font-medium">{label}</span>
        <span className="block font-semibold -mt-[1px]">{value}</span>
      </span>
      <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
    </button>
  );
}
