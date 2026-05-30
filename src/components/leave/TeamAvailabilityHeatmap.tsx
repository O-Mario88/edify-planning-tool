"use client";

import Link from "next/link";
import { Lock } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  teamAvailability,
  teamAvailabilityWeeks,
  type AvailabilityCell,
} from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

const cellStyle: Record<AvailabilityCell, string> = {
  Available:        "bg-emerald-100 text-emerald-800",
  "On Leave":       "bg-teal-200 text-teal-900",
  "Conference Week":"bg-violet-200 text-violet-900",
  "High Load":      "bg-amber-200 text-amber-900",
  Blocked:          "bg-[#e2e8f0] text-[#334155]",
};

export function TeamAvailabilityHeatmap() {
  return (
    <SectionCard
      title="Team Availability by Week"
      actions={
        <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/reports">
          View full report
        </Link>
      }
    >
      {/* Match the scroll-card pattern used by the Upcoming Leave +
          Holiday tables on the left so the three cards in the row
          balance to the same height. */}
      <div className="flex-1 min-h-0 overflow-auto max-h-[420px] -mx-1 px-1">
        <div className="text-[10px] muted text-right pr-1 mb-1">Week (2025)</div>
        <table className="w-full">
          <thead>
            <tr>
              <th scope="col" className="text-left px-2 py-1 text-[11px] muted font-semibold uppercase">Staff</th>
              {teamAvailabilityWeeks.map((w) => (
                <th key={w} className="px-1.5 py-1 text-caption muted font-semibold tabular text-center whitespace-nowrap">
                  {w}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {teamAvailability.map((r) => (
              <tr key={r.staffId}>
                <td className="text-body font-semibold px-2 py-1 whitespace-nowrap">{r.staffName}</td>
                {r.cells.map((c, i) => (
                  <td key={i} className="px-1 py-0.5">
                    <div
                      className={cn(
                        "h-7 rounded-md flex items-center justify-center text-caption font-bold",
                        cellStyle[c],
                      )}
                      title={c}
                    >
                      {c === "Blocked" ? <Lock size={10} /> : null}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] muted">
        <Legend swatch="bg-emerald-100" label="Available" />
        <Legend swatch="bg-teal-200" label="On Leave" />
        <Legend swatch="bg-violet-200" label="Conference Week" />
        <Legend swatch="bg-amber-200" label="High Load" />
        <span className="inline-flex items-center gap-1.5">
          <Lock size={10} className="text-[var(--color-edify-muted)]" />
          Blocked
        </span>
      </div>
    </SectionCard>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("w-3 h-3 rounded", swatch)} />
      {label}
    </span>
  );
}
