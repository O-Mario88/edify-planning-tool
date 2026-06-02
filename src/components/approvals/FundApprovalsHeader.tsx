"use client";

import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ExportButton } from "@/components/ui/ExportButton";

export type ApprovalExportRow = Record<string, unknown>;

// Thin adapter over <PageHeader>. Export rides the actions slot; the live
// filter bar + per-row approve live in the workbench below, so the header
// stays focused (no duplicate filter chip, no non-functional bulk CTA).
export function FundApprovalsHeader({ exportRows = [] }: { exportRows?: ApprovalExportRow[] }) {
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
        <ExportButton
          rows={exportRows}
          filename="fund-approvals"
          className="!h-10 !px-3.5 !rounded-xl bg-white"
        />
      }
    />
  );
}
