"use client";

import { MapPin, CalendarDays } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import { teamTargetsHeader } from "@/lib/team-targets-mock";

// Thin adapter over the canonical <PageHeader>. Was previously a
// bespoke EntityHeader-based header with its own bell + profile chip.
//
// Now delegates everything (title, subtitle, filter pills, search,
// breadcrumbs, avatar menu, ⌘K) to PageHeader for cross-page
// consistency. Filter values are local mock state because the wiring
// isn't built yet — when it is, this will swap to the controlled
// version without changing the visual.
export function TeamTargetsHeader() {
  const filters: PageHeaderFilter[] = [
    { Icon: MapPin,       label: teamTargetsHeader.filters.region },
    { Icon: CalendarDays, label: teamTargetsHeader.filters.month  },
  ];
  return (
    <PageHeader
      title={teamTargetsHeader.title}
      subtitle={teamTargetsHeader.subtitle}
      filters={filters}
      searchPlaceholder={teamTargetsHeader.searchPlaceholder}
    />
  );
}
