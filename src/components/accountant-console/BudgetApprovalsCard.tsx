"use client";

import { ArrowUpRight, CheckCircle2, Clock } from "lucide-react";
import {
  approvalFlow,
  monthlyBudget,
  periodLabel,
  type PlanCostLine,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const DOT_TONE: Record<PlanCostLine["tone"], { dot: string; bar: string }> = {
  emerald: { dot: "bg-emerald-500", bar: "from-emerald-400 to-emerald-600" },
  blue:    { dot: "bg-sky-500",     bar: "from-sky-400     to-sky-600" },
  rose:    { dot: "bg-rose-500",    bar: "from-rose-400    to-rose-600" },
  amber:   { dot: "bg-amber-500",   bar: "from-amber-400   to-amber-600" },
  slate:   { dot: "bg-slate-400",   bar: "from-slate-300   to-slate-500" },
};

// May 2025 Budget & Approvals card.
//
// Left column tells *what was budgeted* — country total + line items with
// inline progress bars. Right column tells *where every approval stands*
// — a 4-step vertical timeline with status pill per step.
export function BudgetApprovalsCard() {
  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-center justify-between gap-2 mb-4 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900">
            {periodLabel}
            {" "}Budget &amp; Approvals
          </h3>
        </div>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-[10px] font-extrabold bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/70">
          <CheckCircle2 size={11} strokeWidth={2.4} />
          Approved by {monthlyBudget.approvedBy}
        </span>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 lg:gap-5 min-w-0">
        {/* Country Monthly Budget */}
        <div className="min-w-0">
          <div className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.1em] mb-1">
            Country Monthly Budget
          </div>
          <div className="text-[30px] xl:text-[32px] font-extrabold tabular num-hero glow-emerald text-slate-900 leading-none mb-4 tracking-tight">
            UGX 1.20B
          </div>
          <ul className="flex flex-col gap-2.5">
            {monthlyBudget.lines.map((l) => {
              const tone = DOT_TONE[l.tone];
              const widthNum = parseInt(l.pct.replace("%", ""), 10);
              return (
                <li key={l.label} className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={cn("w-2 h-2 rounded-full shrink-0", tone.dot)} />
                    <span className="flex-1 text-[11.5px] font-semibold text-slate-700 truncate">
                      {l.label}
                    </span>
                    <span className="text-[11.5px] font-extrabold tabular text-slate-900 num-hero shrink-0">
                      {l.amount}
                    </span>
                    <span className="text-caption text-slate-400 font-semibold tabular w-[28px] text-right shrink-0">
                      {l.pct}
                    </span>
                  </div>
                  <div className="h-[3px] rounded-full bg-slate-100 overflow-hidden ml-4">
                    <div
                      className={cn("h-full rounded-full bg-gradient-to-r", tone.bar)}
                      style={{ width: `${widthNum}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="mt-4 pt-3 border-t border-dashed border-[var(--color-edify-divider)] flex items-center justify-between gap-2 flex-wrap">
            <span className="text-caption text-slate-500 font-semibold">
              Approved by {monthlyBudget.approvedBy} on {monthlyBudget.approvedOn}
            </span>
            <a
              href="#budget-details"
              className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
            >
              View Budget Details →
            </a>
          </div>
        </div>

        {/* Approval Flow */}
        <div className="min-w-0">
          <div className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.1em] mb-2">
            Approval Flow
            <span className="font-semibold normal-case tracking-normal text-slate-400 ml-1">
              (This Month)
            </span>
          </div>
          <ol className="flex flex-col gap-3 relative pl-0">
            <span className="absolute left-[6.5px] top-3 bottom-3 w-px bg-gradient-to-b from-emerald-400 via-emerald-400 to-amber-400" />
            {approvalFlow.map((step, i) => {
              const inProgress = step.status === "In Progress";
              const last = i === approvalFlow.length - 1;
              return (
                <li key={step.role} className="relative flex items-start gap-3 min-w-0">
                  <span
                    className={cn(
                      "w-[14px] h-[14px] rounded-full mt-0.5 shrink-0 z-10 grid place-items-center ring-2 ring-white",
                      inProgress
                        ? "bg-amber-400"
                        : "bg-emerald-500",
                    )}
                  >
                    {inProgress ? (
                      <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                    ) : (
                      <CheckCircle2 size={9} className="text-white" strokeWidth={3} />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="min-w-0">
                        <span className="text-body font-extrabold text-slate-900">
                          {step.role}
                        </span>
                        <span className="text-[11px] text-slate-500 font-semibold ml-1">
                          {step.label}
                        </span>
                      </div>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 px-2 py-[2px] rounded-full text-[9.5px] font-extrabold whitespace-nowrap ring-1",
                          inProgress
                            ? "bg-amber-50 text-amber-700 ring-amber-200/70"
                            : "bg-emerald-50 text-emerald-700 ring-emerald-200/70",
                        )}
                      >
                        {inProgress ? <Clock size={9} strokeWidth={2.4} /> : <CheckCircle2 size={9} strokeWidth={2.4} />}
                        {step.status}
                      </span>
                    </div>
                    <div className="text-caption text-slate-500 font-semibold mt-0.5 flex items-center justify-between gap-2 flex-wrap">
                      {step.meta && <span className="truncate">{step.meta}</span>}
                      <span className="ml-auto">{step.date}</span>
                    </div>
                    {!last && (
                      <div className="mt-2.5 h-px bg-[#F1F4F7]" aria-hidden />
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          <a
            href="#all-approvals"
            className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
          >
            View All approvals
            <ArrowUpRight size={11} />
          </a>
        </div>
      </div>
    </article>
  );
}
