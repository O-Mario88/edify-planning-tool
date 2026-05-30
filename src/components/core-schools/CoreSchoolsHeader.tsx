"use client";

import { Building2, CalendarRange, Download, Layers, Users } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";

// Slim header chrome for the Core Schools route. Now a thin adapter
// over <PageHeader>: filter pills (FY · CCEOs · Districts · Package
// Status) ride the canonical chrome, Export rides the actions slot.
export function CoreSchoolsHeader() {
  const filters: PageHeaderFilter[] = [
    { Icon: CalendarRange, label: "FY 2024/25"            },
    { Icon: Users,         label: "All CCEOs"             },
    { Icon: Building2,     label: "All Districts"         },
    { Icon: Layers,        label: "All Package Statuses"  },
  ];
  return (
    <PageHeader
      title="Core School Dashboard"
      filters={filters}
      actions={
        <button
          type="button"
          className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5 text-slate-700 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
        >
          <Download size={12} className="text-[var(--color-edify-muted)]" />
          Export
        </button>
      }
    />
  );
}
