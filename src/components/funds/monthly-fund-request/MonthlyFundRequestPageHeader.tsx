"use client";

// MonthlyFundRequestPageHeader — page chrome adapter.
//
// Thin wrapper over the canonical <PageHeader> so the MFR page picks
// up the same full-width chrome every other shell page has: title,
// subtitle, search bar, notification bell, messages inbox, and
// avatar menu on the right. Without this the MFR page rendered with
// no top header, which broke the consistency with /approvals,
// /core-schools, etc.
//
// Page-specific actions (Export + the canonical demo role hint) ride
// the `actions` slot so the rest of the chrome (bell, messages,
// avatar) sits to their right.

import { Download, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

export function MonthlyFundRequestPageHeader({
  monthLabel,
  countryName,
}: {
  monthLabel: string;
  countryName: string;
}) {
  return (
    <PageHeader
      title="Monthly Fund Request"
      subtitle={`${monthLabel} · ${countryName} · Auto-generated from approved monthly plans + active CD cost settings.`}
      // The live staff/partner search lives in MfrStaffFilter; the header
      // slot falls back to the global ⌘K palette (no duplicate search box).
      titleBadge={
        <button
          type="button"
          aria-label="About the Monthly Fund Request"
          className="w-5 h-5 rounded-full grid place-items-center text-slate-400 hover:text-slate-600 transition-colors"
        >
          <Info size={14} />
        </button>
      }
      actions={
        <button
          type="button"
          aria-label="Export this request"
          className="inline-flex items-center justify-center gap-1.5 h-10 px-3.5 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
        >
          <Download size={13} />
          <span className="hidden sm:inline">Export</span>
        </button>
      }
    />
  );
}
