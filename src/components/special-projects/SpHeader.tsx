"use client";

import { Calendar, MapPin, Layers, Handshake, ChevronDown } from "lucide-react";
import { EntityHeader } from "@/components/ui/EntityHeader";
import {
  specialProjectsHeader,
  specialProjectsHeaderUser,
  specialProjectsNotificationCount,
} from "@/lib/special-projects-mock";

export function SpHeader() {
  return (
    <EntityHeader
      title={specialProjectsHeader.title}
      subtitle={specialProjectsHeader.subtitle}
      filters={
        <>
          <FilterPill value={specialProjectsHeader.filters.month}       Icon={Calendar} />
          <FilterPill value={specialProjectsHeader.filters.region}      Icon={MapPin} />
          <FilterPill value={specialProjectsHeader.filters.projectType} Icon={Layers} />
          <FilterPill value={specialProjectsHeader.filters.partner}     Icon={Handshake} />
        </>
      }
      search={{ placeholder: specialProjectsHeader.searchPlaceholder }}
      messages={{ count: 3 }}
      notifications={{ count: specialProjectsNotificationCount }}
      profile={{ name: specialProjectsHeaderUser.name, initials: specialProjectsHeaderUser.initials }}
    />
  );
}

function FilterPill({
  value,
  Icon,
}: {
  value: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}) {
  return (
    <button
      type="button"
      className="h-10 pl-3 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center gap-2 text-[13px] min-w-[150px]"
    >
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="font-semibold flex-1 text-left whitespace-nowrap">{value}</span>
      <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
    </button>
  );
}
