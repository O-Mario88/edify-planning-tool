"use client";

import { CheckCircle2, Download, Info, Plus } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

// CD-scope fund approvals header — title + info badge + subtitle + 3
// actions (Export, Approve All Valid, Create Admin Fund Request). Now
// a thin adapter over <PageHeader>.
export function CountryFundApprovalsHeader({
  onCreateRequest,
}: {
  onCreateRequest?: () => void;
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
          <button
            type="button"
            aria-label="Export"
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors shrink-0"
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
