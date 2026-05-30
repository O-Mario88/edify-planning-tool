"use client";

import { ChevronDown, Download } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { rvpFundFilters } from "@/lib/rvp-fund-approvals-mock";

// RVP-scope fund approvals — title + subtitle + Financial Year /
// Quarter / Status filter pills + Export. Now a thin adapter over
// <PageHeader>. The shell-level NotificationBell handles the bell.
export function RvpFundApprovalsHeader() {
  return (
    <PageHeader
      title="RVP Fund Approval"
      subtitle="Approve and monitor all country funds requests. Select a country to review plans, budgets, and requests."
      actions={
        <>
          <FilterPill label="FY" value={rvpFundFilters.fy} />
          <FilterPill label="Quarter" value={rvpFundFilters.quarter} />
          <FilterPill label="Status" value={rvpFundFilters.status} />
          <button
            type="button"
            className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-body font-extrabold transition-colors shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
          >
            <Download size={13} />
            Export
          </button>
        </>
      }
    />
  );
}

function FilterPill({ label, value }: { label: string; value: string }) {
  return (
    <button
      type="button"
      className="card card-lift inline-flex items-center gap-1.5 h-10 px-2.5 rounded-xl cursor-default"
    >
      <span className="text-[9.5px] muted font-bold uppercase tracking-wide hidden sm:inline">{label}</span>
      <span className="text-[11.5px] font-extrabold text-slate-900 num-hero">{value}</span>
      <ChevronDown size={12} className="text-slate-400" />
    </button>
  );
}
