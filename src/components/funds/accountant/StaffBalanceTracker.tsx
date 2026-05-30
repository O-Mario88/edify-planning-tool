"use client";

import { AlertTriangle, ArrowUpRight } from "lucide-react";
import { staffBalances } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";

// Staff Balance Tracker.
//
// Rolling outstanding-funds register per staff. A flagged row (red)
// means the staff has open funds for ≥ 2 weeks — the next-release
// gate should fire for them.
export function StaffBalanceTracker() {
  const sorted = [...staffBalances].sort(
    (a, b) => b.outstanding.amount - a.outstanding.amount,
  );

  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Staff Balance Tracker</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Rolling outstanding · accountability gate input
          </p>
        </div>
        <a
          href="#staff-ledger"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)]"
        >
          Full ledger
          <ArrowUpRight size={10} />
        </a>
      </header>

      <ul className="flex flex-col gap-1.5">
        {sorted.map((s, i) => {
          const stagger = `stagger-${(i % 6) + 1}`;
          return (
            <li
              key={s.staffId}
              className={cn(
                "rounded-xl border bg-white p-2.5 flex items-center gap-2.5 card-lift tile-in",
                s.flagged
                  ? "border-rose-200 bg-rose-50/40"
                  : "border-[var(--color-edify-border)]",
                stagger,
              )}
            >
              <span className="w-7 h-7 rounded-full grid place-items-center text-[10px] font-extrabold text-white shrink-0 bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]">
                {s.staffName.split(" ").map((p) => p[0]).join("").slice(0, 2)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold text-slate-900 truncate">
                  {s.staffName}
                </div>
                <div className="text-[10px] muted font-semibold truncate">
                  {s.district} · {s.weeksOutstanding} open week{s.weeksOutstanding === 1 ? "" : "s"}
                  {s.oldestWeekIso && ` · oldest ${s.oldestWeekIso}`}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                  {formatMoney(s.outstanding)}
                </div>
                <div className="text-[9.5px] muted font-semibold mt-0.5">outstanding</div>
              </div>
              {s.flagged && (
                <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold bg-rose-100 text-rose-700 border border-rose-200 shrink-0">
                  <AlertTriangle size={9} />
                  Gate
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </article>
  );
}
