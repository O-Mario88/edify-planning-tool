"use client";

import { CheckCircle2, ChevronDown, Download, Filter, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

// Thin adapter over <PageHeader>. The "Approve All Valid" CTA, Export,
// and Filters chips ride the actions slot; everything else (title,
// subtitle, breadcrumbs, search, bell, avatar) comes from the
// canonical chrome.
export function FundApprovalsHeader() {
  return (
    <PageHeader
      title="Fund Approvals"
      subtitle="All fund requests are derived from CCEO plans. You approve only funds for your own team."
      titleBadge={
        <button
          type="button"
          aria-label="About fund approvals"
          className="w-5 h-5 rounded-full grid place-items-center text-slate-400 hover:text-slate-600 transition-colors"
        >
          <Info size={14} />
        </button>
      }
      actions={
        <>
          <button
            type="button"
            aria-label="Export"
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
          >
            <Download size={13} />
            <span className="hidden sm:inline">Export</span>
          </button>
          <button
            type="button"
            className="btn btn-primary inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl text-body font-extrabold"
          >
            <CheckCircle2 size={13} />
            <span className="truncate">Approve All Valid</span>
          </button>
          <button
            type="button"
            aria-label="Filters"
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
          >
            <Filter size={13} />
            <span className="hidden sm:inline">Filters</span>
            <ChevronDown size={12} className="hidden sm:block text-slate-400" />
          </button>
        </>
      }
    />
  );
}
