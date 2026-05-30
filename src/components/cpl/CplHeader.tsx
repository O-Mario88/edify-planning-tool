"use client";

import Link from "next/link";
import { Calendar, MapPin, Download, Brain, Plus } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import { cplHeader } from "@/lib/cpl-mock";

// CplHeader — thin adapter over <PageHeader>. CPL-specific direct
// CTAs (Plan a Visit, Submit Debrief, Export) ride the actions slot;
// title, subtitle, search, filter pills, bell, avatar all come from
// the canonical chrome.
export function CplHeader() {
  const filters: PageHeaderFilter[] = [
    { Icon: Calendar, label: cplHeader.filters.financialYear },
    { Icon: Calendar, label: cplHeader.filters.month },
    { Icon: MapPin,   label: cplHeader.filters.regionCountry },
  ];
  return (
    <PageHeader
      title={cplHeader.title}
      subtitle={cplHeader.subtitle}
      filters={filters}
      searchPlaceholder={cplHeader.searchPlaceholder}
      actions={
        <>
          <Link
            href="/plans/new"
            className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Plus size={13} />
            Plan a Visit
          </Link>
          <Link
            href="/field-intelligence"
            className="h-10 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-body font-semibold inline-flex items-center gap-1.5 shadow-sm shadow-emerald-500/25"
          >
            <Brain size={13} />
            Submit Debrief
          </Link>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-10 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] text-body font-semibold hover:bg-[var(--color-edify-soft)]/40"
          >
            <Download size={14} />
            Export
          </button>
        </>
      }
    />
  );
}
