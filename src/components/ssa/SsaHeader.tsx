"use client";

import {
  Calendar,
  CalendarRange,
  CalendarClock,
  ChevronDown,
  MapPin,
  Building2,
} from "lucide-react";
import { EntityHeader } from "@/components/ui/EntityHeader";
import { ssaHeader, ssaUser, ssaNotificationCount } from "@/lib/ssa-mock";

// Thin adapter over <EntityHeader/>. SsaHero used to own the title, but
// it's been retired in the global hero removal pass — the header now
// carries the page identity (title + subtitle) and full chrome
// (filters, search, mail, notifications, profile).
export function SsaHeader() {
  return (
    <EntityHeader
      title={ssaHeader.title}
      subtitle={ssaHeader.subtitle}
      filters={
        <>
          <LabeledPill label="Financial Year" value={ssaHeader.filters.financialYear} Icon={CalendarClock} />
          <LabeledPill label="Quarter"        value={ssaHeader.filters.quarter}       Icon={CalendarRange} />
          <LabeledPill label="Region"         value={ssaHeader.filters.region}        Icon={MapPin} />
          <LabeledPill label="District"       value={ssaHeader.filters.district}      Icon={Building2} />
          <button
            type="button"
            className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1"
          >
            <Calendar size={11} />
            Reset
          </button>
        </>
      }
      search={{ placeholder: ssaHeader.searchPlaceholder }}
      messages={{ count: 3 }}
      notifications={{ count: ssaNotificationCount }}
      profile={{ name: ssaUser.name, initials: ssaUser.initials }}
    />
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
    <button
      type="button"
      className="h-10 pl-3 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center gap-2 text-[13px] min-w-[150px]"
    >
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="leading-tight text-left flex-1">
        <span className="block text-[10px] text-[var(--color-edify-muted)] font-medium">{label}</span>
        <span className="block font-semibold -mt-[1px]">{value}</span>
      </span>
      <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
    </button>
  );
}
