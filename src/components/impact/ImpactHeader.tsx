"use client";

import { Calendar, Briefcase, MapPin, ChevronDown, HelpCircle } from "lucide-react";
import Link from "next/link";
import { EntityHeader } from "@/components/ui/EntityHeader";
import {
  impactHeader,
  impactUser,
  impactNotificationCount,
} from "@/lib/impact-mock";

export function ImpactHeader() {
  return (
    <EntityHeader
      title={impactHeader.title}
      subtitle={impactHeader.subtitle}
      filters={
        <>
          <FilterPill label={impactHeader.filters.month}   Icon={Calendar}  />
          <FilterPill label={impactHeader.filters.program} Icon={Briefcase} />
          <FilterPill label={impactHeader.filters.region}  Icon={MapPin}    />
        </>
      }
      search={{ placeholder: "Search records…" }}
      messages={{ count: 3 }}
      notifications={{ count: impactNotificationCount }}
      profile={{ name: impactUser.name, initials: impactUser.initials }}
      actions={
        <Link
          href="/help"
          aria-label="Help"
          prefetch={false}
          className="h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-center text-[var(--color-edify-muted)]"
        >
          <HelpCircle size={16} />
        </Link>
      }
    />
  );
}

function FilterPill({
  label,
  Icon,
}: {
  label: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}) {
  return (
    <button
      type="button"
      className="h-10 pl-3 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center gap-2 text-[13px] min-w-[150px]"
    >
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="leading-tight text-left flex-1 font-semibold">{label}</span>
      <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
    </button>
  );
}
