"use client";

import { Send } from "lucide-react";
import { disbursementSummary } from "@/lib/accountant-console-mock";

// Disbursement Summary — a simple, chart-free overview.
//
// Replaces the weekly line chart with scannable numbers:
//   • Hero — total disbursed this month
//   • A single split bar — disbursed vs still-in-queue
//   • Three legend rows — Approved · Disbursed · In Queue
//   • A weekly list with proportional bars
export function DisbursementSummary() {
  const s = disbursementSummary;

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-start justify-between gap-2 mb-3">
        <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900">
          Disbursement Summary
        </h3>
        <span className="text-caption text-slate-500 font-semibold">This Month</span>
      </header>

      {/* Hero */}
      <div className="flex items-center gap-2.5 mb-3">
        <span className="w-10 h-10 rounded-xl grid place-items-center bg-emerald-50 shrink-0">
          <Send size={17} className="text-emerald-600" strokeWidth={2.2} />
        </span>
        <div className="min-w-0">
          <div className="text-[26px] xl:text-[28px] font-extrabold tabular num-hero glow-emerald text-slate-900 leading-none">
            {s.disbursedTotal}
          </div>
          <div className="text-caption text-slate-500 font-semibold mt-1">
            Disbursed across {s.disbursedCount} disbursements
          </div>
        </div>
      </div>

      {/* Split bar — disbursed vs in-queue */}
      <div className="h-2.5 rounded-full bg-slate-100 overflow-hidden flex mb-3">
        <div
          className="h-full bg-gradient-to-r from-emerald-400 to-emerald-600"
          style={{ width: `${s.disbursedPct}%` }}
        />
        <div
          className="h-full bg-gradient-to-r from-amber-300 to-amber-500"
          style={{ width: `${s.pendingPct}%` }}
        />
      </div>

      {/* Legend rows */}
      <ul className="flex flex-col gap-2 mb-4">
        <LegendRow dot="bg-slate-300" label="Approved this month" amount={s.approvedTotal} />
        <LegendRow dot="bg-emerald-500" label="Disbursed" amount={s.disbursedTotal} pct={`${s.disbursedPct}%`} />
        <LegendRow dot="bg-amber-500" label="Still in queue" amount={s.pendingTotal} pct={`${s.pendingPct}%`} />
      </ul>

      {/* Weekly breakdown */}
      <div className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.1em] mb-2">
        Weekly Breakdown
      </div>
      <ul className="flex flex-col gap-2.5 flex-1">
        {s.weekly.map((w, i) => (
          <li
            key={w.week}
            className={`flex items-center gap-2.5 min-w-0 tile-in stagger-${i + 1}`}
          >
            <div className="w-[42px] shrink-0">
              <div className="text-[11px] font-extrabold text-slate-900 leading-none">
                {w.week}
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="h-[5px] rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-sky-400 to-sky-600"
                  style={{ width: `${w.pct}%` }}
                />
              </div>
              <div className="text-[9.5px] text-slate-400 font-semibold mt-1 truncate">
                {w.range}
              </div>
            </div>
            <div className="text-[12px] font-extrabold tabular num-hero text-slate-900 shrink-0 w-[72px] text-right">
              {w.amount}
            </div>
          </li>
        ))}
      </ul>

      <a
        href="#weekly-breakdown"
        className="mt-3 self-start inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View weekly breakdown →
      </a>
    </article>
  );
}

function LegendRow({
  dot,
  label,
  amount,
  pct,
}: {
  dot: string;
  label: string;
  amount: string;
  pct?: string;
}) {
  return (
    <li className="flex items-center gap-2 min-w-0">
      <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
      <span className="flex-1 text-[11.5px] font-semibold text-slate-600 truncate">
        {label}
      </span>
      {pct && (
        <span className="text-[10px] text-slate-400 font-semibold tabular shrink-0">
          {pct}
        </span>
      )}
      <span className="text-body font-extrabold tabular num-hero text-slate-900 shrink-0 w-[84px] text-right">
        {amount}
      </span>
    </li>
  );
}
