"use client";

import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ExportButton } from "@/components/ui/ExportButton";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import type { FilterScope } from "@/lib/filters/types";

export type ApprovalExportRow = Record<string, unknown>;

// Thin adapter over <PageHeader>. Export rides the actions slot; the LIVE
// region/district filter bar scopes the queue (the page reads the same URL
// via selectionFromSearchParams). Replaces the old static
// FundApprovalsFilterBar, whose dropdowns + search did nothing.
export function FundApprovalsHeader({
  exportRows = [],
  filterScope,
}: {
  exportRows?: ApprovalExportRow[];
  filterScope?: FilterScope;
}) {
  return (
    <PageHeader
      title="Fund Approvals"
      subtitle="All fund requests are derived from CCEO plans. You approve only funds for your own team."
      filterBar={filterScope ? <HeaderFilterBar scope={filterScope} /> : undefined}
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
        <ExportButton
          rows={exportRows}
          filename="fund-approvals"
          className="!h-10 !px-3.5 !rounded-xl bg-white"
        />
      }
    />
  );
}
