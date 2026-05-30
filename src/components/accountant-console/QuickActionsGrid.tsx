"use client";

import {
  Banknote,
  ClipboardCheck,
  Download,
  FileSpreadsheet,
  Landmark,
  PauseCircle,
  Send,
  Timer,
  type LucideIcon,
} from "lucide-react";
import {
  quickActions,
  type QuickAction,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const ACT_ICON: Record<QuickAction["iconKey"], LucideIcon> = {
  logFunds:     Banknote,
  disburse:     Send,
  partial:      Timer,
  hold:         PauseCircle,
  exportLedger: Download,
  reconcile:    Landmark,
  report:       FileSpreadsheet,
  audit:        ClipboardCheck,
};

const TONE: Record<
  QuickAction["tone"],
  { bg: string; fg: string; hover: string }
> = {
  emerald: { bg: "bg-emerald-50",  fg: "text-emerald-600", hover: "hover:bg-emerald-50/60" },
  blue:    { bg: "bg-sky-50",      fg: "text-sky-600",     hover: "hover:bg-sky-50/60" },
  amber:   { bg: "bg-amber-50",    fg: "text-amber-600",   hover: "hover:bg-amber-50/60" },
  rose:    { bg: "bg-rose-50",     fg: "text-rose-600",    hover: "hover:bg-rose-50/60" },
  violet:  { bg: "bg-violet-50",   fg: "text-violet-600",  hover: "hover:bg-violet-50/60" },
  slate:   { bg: "bg-slate-50",    fg: "text-slate-600",   hover: "hover:bg-slate-50/80" },
};

// Quick Actions — horizontal action bar across the full dashboard width.
//
// 8 tiles, each with icon + label inline. Tile width grows with viewport
// so the bar fills the row without dead space. Two visual groups:
//   1–4: operations  (Log Funds Received · Disburse · Partial · Hold)
//   5–8: records     (Export Ledger · Reconciliation · Report · Audit)
// A subtle divider sits between the two groups so the user can scan the
// group affordance instantly.
export function QuickActionsGrid() {
  return (
    <article className="card p-3 lg:p-4 flex flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-2 mb-2.5 px-1">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight text-slate-900">
            Quick Actions
          </h3>
        </div>
        <span className="text-[10px] text-slate-400 font-semibold">
          Operations &nbsp;·&nbsp; Records
        </span>
      </header>
      <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
        {quickActions.map((a, i) => {
          const Icon = ACT_ICON[a.iconKey];
          const tone = TONE[a.tone];
          const isDivider = i === 4; // start of the records group
          return (
            <button
              key={a.key}
              type="button"
              className={cn(
                "relative rounded-xl ring-1 ring-[var(--color-edify-border)] bg-white transition-all duration-200 p-2.5 flex items-center gap-2 tile-in text-left group min-w-0",
                "hover:-translate-y-0.5 hover:shadow-[0_8px_20px_-10px_rgba(15,23,32,0.18)] hover:ring-slate-300",
                tone.hover,
                isDivider && "md:ml-2.5 md:before:content-[''] md:before:absolute md:before:-left-2.5 md:before:top-1/2 md:before:-translate-y-1/2 md:before:h-6 md:before:w-px md:before:bg-[#E5E9EE]",
                `stagger-${(i % 8) + 1}`,
              )}
            >
              <span
                className={cn(
                  "w-9 h-9 rounded-lg grid place-items-center shrink-0 transition-transform group-hover:scale-110",
                  tone.bg,
                )}
                aria-hidden
              >
                <Icon size={15} className={tone.fg} strokeWidth={2.2} />
              </span>
              <span className="text-caption font-extrabold text-slate-700 leading-[1.15] line-clamp-2 min-w-0 flex-1">
                {a.label}
              </span>
            </button>
          );
        })}
      </div>
    </article>
  );
}
