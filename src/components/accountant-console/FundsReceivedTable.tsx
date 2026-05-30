"use client";

import { ArrowDownLeft } from "lucide-react";
import { fundsReceivedRows } from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

// Funds Received (This Month).
//
// Clean inflow register — every wire / top-up that has landed in the
// country account during the current period. Each amount carries a
// tiny inflow arrow + emerald accent so the inflow story reads at a
// glance.
export function FundsReceivedTable() {
  return (
    <article className="card p-5 lg:p-6 flex flex-col overflow-hidden h-full">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900 inline-flex items-baseline gap-1.5">
            Funds Received
            <span className="text-caption text-slate-500 font-semibold normal-case tracking-normal">(This Month)</span>
          </h3>
        </div>
      </header>

      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.08em] border-b border-[var(--color-edify-divider)]">
              <th scope="col" className="text-left  py-2.5 pr-3">Date</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Source</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Description</th>
              <th scope="col" className="text-right py-2.5 pr-3">Amount (UGX)</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Reference</th>
              <th scope="col" className="text-left  py-2.5">Received By</th>
            </tr>
          </thead>
          <tbody>
            {fundsReceivedRows.map((r, i) => (
              <tr
                key={r.reference}
                className={cn(
                  "border-b border-[#F4F6F8] last:border-b-0 hover:bg-slate-50/60 transition-colors tile-in",
                  `stagger-${(i % 6) + 1}`,
                )}
              >
                <td className="py-3 pr-3 text-[11.5px] font-semibold text-slate-700 whitespace-nowrap tabular">
                  {r.date}
                </td>
                <td className="py-3 pr-3 text-[11.5px] font-semibold text-slate-700 whitespace-nowrap">
                  {r.source}
                </td>
                <td className="py-3 pr-3 text-[11.5px] text-slate-700 max-w-[260px] truncate">
                  {r.description}
                </td>
                <td className="py-3 pr-3 text-right whitespace-nowrap">
                  <span className="inline-flex items-center justify-end gap-1 text-[12px] font-extrabold tabular num-hero text-emerald-700">
                    <ArrowDownLeft size={11} strokeWidth={2.4} className="text-emerald-500" />
                    {r.amountUgx.toLocaleString()}
                  </span>
                </td>
                <td className="py-3 pr-3 text-[11px] font-extrabold tabular text-sky-700 whitespace-nowrap">
                  {r.reference}
                </td>
                <td className="py-3 text-[11.5px] font-semibold text-slate-700 whitespace-nowrap">
                  {r.receivedBy}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <a
        href="#funds-received-all"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All transactions →
      </a>
    </article>
  );
}
