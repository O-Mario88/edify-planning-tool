"use client";

import { AlertCircle, ArrowUpRight, Bell, CheckCircle2, Clock } from "lucide-react";
import {
  expenseIdSummary,
  topOutstandingExpenseIds,
  type ExpenseIdRow,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const ROW_TONE: Record<
  ExpenseIdRow["tone"],
  { bg: string; fg: string; bar: string; Icon: typeof CheckCircle2 }
> = {
  emerald: { bg: "bg-emerald-50",  fg: "text-emerald-600", bar: "from-emerald-400 to-emerald-600", Icon: CheckCircle2 },
  amber:   { bg: "bg-amber-50",    fg: "text-amber-600",   bar: "from-amber-400   to-amber-600",   Icon: Clock },
  rose:    { bg: "bg-rose-50",     fg: "text-rose-600",    bar: "from-rose-400    to-rose-600",    Icon: AlertCircle },
};

// Accountability Summary — three buckets of accountability state.
//
// Submitted on time (emerald) · Pending submission (amber) · Overdue
// (rose). Each row is a label + amount + percentage with a thin
// progress bar that reads the share at a glance.
export function AccountabilitySummary() {
  return (
    <article className="card p-4 lg:p-5 flex flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight text-slate-900">
            Accountability Summary
          </h3>
        </div>
      </header>
      <ul className="flex flex-col gap-3">
        {expenseIdSummary.map((r, i) => {
          const tone = ROW_TONE[r.tone];
          const Icon = tone.Icon;
          const pctNum = parseInt(r.pct.replace("%", ""), 10);
          return (
            <li
              key={r.label}
              className={`tile-in stagger-${i + 1} min-w-0`}
            >
              <div className="flex items-center gap-2.5 mb-1.5 min-w-0">
                <span
                  className={cn(
                    "w-8 h-8 rounded-lg grid place-items-center shrink-0",
                    tone.bg,
                  )}
                >
                  <Icon size={13} className={tone.fg} strokeWidth={2.2} />
                </span>
                <div className="min-w-0 flex-1 flex items-center justify-between gap-2">
                  <div className="text-[11.5px] font-semibold text-slate-600 truncate">
                    {r.label}
                  </div>
                  <div className="flex items-baseline gap-1 shrink-0">
                    <span className="text-body font-extrabold tabular text-slate-900 num-hero leading-tight">
                      {r.amount}
                    </span>
                    <span className="text-caption text-slate-400 font-semibold tabular">
                      ({r.pct})
                    </span>
                  </div>
                </div>
              </div>
              <div className="h-[3px] rounded-full bg-slate-100 overflow-hidden">
                <div
                  className={cn("h-full rounded-full bg-gradient-to-r", tone.bar)}
                  style={{ width: `${pctNum}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <a
        href="#accountability-all"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All accountability →
      </a>
    </article>
  );
}

// Top Overdue Accountability — three rows of staff with the longest
// outstanding accountability + days-overdue chip + remind action.
export function TopOverdueAccountability() {
  return (
    <article className="card p-4 lg:p-5 flex flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight text-slate-900">
            Top Overdue Accountability
          </h3>
        </div>
        <a
          href="#awaiting-all"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-sky-700 hover:text-sky-800"
        >
          View All
          <ArrowUpRight size={10} />
        </a>
      </header>
      <ul className="flex flex-col gap-2">
        {topOutstandingExpenseIds.map((row, i) => (
          <li
            key={row.staff}
            className={cn(
              "rounded-xl ring-1 ring-rose-100 bg-rose-50/30 hover:bg-rose-50/60 p-2.5 flex items-center gap-2.5 transition-colors tile-in min-w-0",
              `stagger-${i + 1}`,
            )}
          >
            <span className="w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 bg-gradient-to-br from-rose-400 to-rose-600 shadow-[0_4px_10px_-4px_rgba(244,63,94,0.55)]">
              {row.initials}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-extrabold text-slate-900 truncate">
                {row.staff}{" "}
                <span className="text-slate-400 font-semibold">({row.staffRole})</span>
              </div>
              <div className="text-caption text-slate-500 font-semibold truncate">
                {row.week}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                {row.amount}
              </div>
              <div className="text-[10px] font-extrabold text-rose-600 mt-1">
                {row.daysOverdue} days overdue
              </div>
            </div>
            <button
              type="button"
              title="Send reminder"
              aria-label="Send reminder"
              className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-white ring-1 ring-rose-200 hover:bg-rose-50 hover:ring-rose-300 text-rose-600 shrink-0 transition-colors"
            >
              <Bell size={11} strokeWidth={2.2} />
            </button>
          </li>
        ))}
      </ul>
    </article>
  );
}
