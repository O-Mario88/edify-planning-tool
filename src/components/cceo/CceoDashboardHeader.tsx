"use client";

import { Building2, CalendarRange, GitCompareArrows, Sparkles } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import { cceoDashboardHeader } from "@/lib/cceo-mock";

// Slim Operating View header — now a thin adapter over the canonical
// <PageHeader>. The "Operating View" pill rides in `titleBadge`,
// global search + filter pills + bell + avatar all come from the
// shared chrome.
export function CceoDashboardHeader() {
  const filters: PageHeaderFilter[] = [
    { Icon: CalendarRange,    label: cceoDashboardHeader.filters.month    },
    { Icon: GitCompareArrows, label: cceoDashboardHeader.filters.compare  },
    { Icon: Building2,        label: cceoDashboardHeader.filters.district },
  ];
  return (
    <PageHeader
      title={cceoDashboardHeader.title}
      searchPlaceholder="Search schools, activities, clusters…"
      filters={filters}
      titleBadge={
        <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200 whitespace-nowrap">
          <Sparkles size={9} />
          Operating View
        </span>
      }
    />
  );
}
