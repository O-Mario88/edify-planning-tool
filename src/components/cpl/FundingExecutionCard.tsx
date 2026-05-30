"use client";

import { DollarSign, ArrowUpRight } from "lucide-react";
import { ProgressRing, SectionCard } from "@/components/ui/primitives";
import {
  fundUtilization,
  fundRequestStatus,
  type FundStatusRow,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

// 4-tone discipline:
//   Pending Approval → amber, Approved → edify (informational, blue),
//   Disbursed → emerald (success), Returned / Rejected → rose (critical).
const dotTone: Record<FundStatusRow["tone"], string> = {
  amber: "bg-[var(--color-edify-orange)]",
  green: "bg-[var(--color-success)]",
  blue:  "bg-[var(--color-edify-primary)]",
  red:   "bg-[var(--color-danger)]",
};

export function FundingExecutionCard() {
  return (
    <SectionCard icon={<DollarSign size={13} />} title="Funding & Execution">
      {/* Top — utilization (ring + metadata) in a compact horizontal
          strip so the donut never duels with the status list for the
          same row. From xl up there's enough width to relax the layout
          a touch. */}
      <div className="flex items-center gap-3 lg:gap-4 pb-3 border-b border-[#eef2f4]">
        <ProgressRing
          pct={fundUtilization.pct}
          size={80}
          stroke={8}
          color="var(--color-success)"
          label={`${fundUtilization.pct}%`}
          sublabel="Utilized"
        />
        <div className="min-w-0 flex-1">
          <div className="text-caption muted font-bold uppercase tracking-wide">Monthly Fund Utilization</div>
          <div className="text-[16px] lg:text-[18px] font-extrabold tabular leading-none tracking-tight mt-1 truncate">
            {fundUtilization.utilizedLabel}
          </div>
          <div className="text-[11px] font-semibold mt-1 inline-flex items-center gap-1 text-[var(--color-success)]">
            <ArrowUpRight size={11} />
            {fundUtilization.trend}
          </div>
        </div>
      </div>

      {/* Status list — full width below the utilization strip. */}
      <div className="mt-3 min-w-0">
        <div className="text-caption muted font-bold uppercase tracking-wide mb-1.5">Fund Requests Status</div>
        <div className="space-y-0.5">
          {fundRequestStatus.map((r) => (
            <div
              key={r.key}
              className="flex items-center justify-between gap-2 py-1.5 border-b border-[#eef2f4] last:border-b-0"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className={cn("w-2 h-2 rounded-full inline-block shrink-0", dotTone[r.tone])} />
                <span className="text-[12px] font-semibold truncate">{r.label}</span>
              </div>
              <div className="flex items-baseline gap-1.5 shrink-0 tabular">
                <span className="text-[13.5px] font-extrabold">{r.count}</span>
                <span className="text-caption muted">{r.amountLabel}</span>
              </div>
            </div>
          ))}
        </div>
        <a
          href="#finance"
          className="inline-block mt-2 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          View finance dashboard →
        </a>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted leading-snug">
        <span className="font-semibold text-[var(--color-edify-text)]">Visibility only.</span>{" "}
        Final fund approval flows through the Program Accountant, Country Director, and RVP where required.
      </div>
    </SectionCard>
  );
}
