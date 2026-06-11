"use client";

import { Info, Plus } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ExportButton } from "@/components/ui/ExportButton";

// CD-scope fund approvals header — title + info badge + subtitle + 2
// actions (Export, Create Admin Fund Request). The old dead "Approve All
// Valid" bulk button was removed — bulk-approving money was never wired,
// and the per-row Approve in the queue (CdFundActionButtons, role-checked)
// is the real path. Export now uses the shared ExportButton.
export function CountryFundApprovalsHeader({
  onCreateRequest,
  exportRows = [],
}: {
  onCreateRequest?: () => void;
  exportRows?: Record<string, unknown>[];
}) {
  return (
    <PageHeader
      title="Country Fund Approvals"
      subtitle="Review and approve team fund requests from Program Leads and Special Projects. Country-level admin budget requests are created here."
      titleBadge={
        <button
          type="button"
          aria-label="About country fund approvals"
          className="w-5 h-5 rounded-full grid place-items-center text-slate-400 hover:text-slate-600 transition-colors"
        >
          <Info size={14} />
        </button>
      }
      actions={
        <>
          <ExportButton
            rows={exportRows}
            filename="country-fund-approvals"
            className="!h-10 !px-3.5 !rounded-xl bg-white"
          />
          <button
            type="button"
            onClick={onCreateRequest}
            aria-label="Create Admin Fund Request"
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-body font-extrabold transition-colors shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)] shrink-0"
          >
            <Plus size={13} />
            <span className="hidden sm:inline truncate">
              <span className="lg:hidden">Create Request</span>
              <span className="hidden lg:inline">Create Admin Fund Request</span>
            </span>
          </button>
        </>
      }
    />
  );
}
