"use client";

import { Calendar, MapPin } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import { schoolsHeader } from "@/lib/schools-mock";

// Thin adapter over the canonical <PageHeader>. Replaces the previous
// EntityHeader-based bespoke header. Filter values stay local until
// the backing state lands; everything else — title, subtitle, search,
// breadcrumbs, avatar menu, ⌘K — comes from PageHeader.
export function SchoolsHeader() {
  const filters: PageHeaderFilter[] = [
    { Icon: Calendar, label: schoolsHeader.filters.month  },
    { Icon: MapPin,   label: schoolsHeader.filters.region },
  ];
  return (
    <PageHeader
      title={schoolsHeader.title}
      subtitle={schoolsHeader.subtitle}
      filters={filters}
      searchPlaceholder={schoolsHeader.searchPlaceholder}
    />
  );
}
