"use client";

import { ArrowUpRight, CheckCircle2, Clock } from "lucide-react";
import { recentDisbursements } from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const AVATAR_GRADIENTS = [
  "from-sky-400     to-sky-600",
  "from-violet-400  to-violet-600",
  "from-emerald-400 to-emerald-600",
];

// Recent Disbursements — last 3 releases as a vertical list.
//
// Sits in the right column of Row 5 (col-span-4), so the list reads
// as a stacked feed of recent releases with avatar · staff · purpose
// · amount · accountability state.
export function RecentDisbursementsList() {
  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-center justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900">
            Recent Disbursements
          </h3>
        </div>
        <a
          href="#disb-all"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-sky-700 hover:text-sky-800"
        >
          View All
          <ArrowUpRight size={10} />
        </a>
      </header>
      <ul className="flex flex-col gap-2.5 flex-1">
        {recentDisbursements.map((d, i) => {
          const hasNsId = !!d.netsuiteExpenseId;
          return (
            <li
              key={d.disbursementId}
              className={cn(
                "rounded-xl ring-1 ring-[var(--color-edify-border)] bg-white hover:bg-slate-50/60 hover:ring-slate-300 transition-all p-3 flex items-center gap-3 tile-in min-w-0",
                `stagger-${i + 1}`,
              )}
            >
              <span
                className={cn(
                  "w-10 h-10 rounded-full grid place-items-center text-[11.5px] font-extrabold text-white shrink-0 bg-gradient-to-br shadow-[0_4px_10px_-4px_rgba(15,23,32,0.35)]",
                  AVATAR_GRADIENTS[i % AVATAR_GRADIENTS.length],
                )}
              >
                {d.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold text-slate-900 truncate">
                  {d.staff}{" "}
                  <span className="text-slate-400 font-semibold">({d.staffRole})</span>
                </div>
                <div className="text-caption text-slate-500 font-semibold truncate">
                  {d.purpose}
                </div>
                {hasNsId ? (
                  <div className="text-[9.5px] mt-0.5 inline-flex items-center gap-1 font-extrabold text-emerald-700">
                    <CheckCircle2 size={9} strokeWidth={2.6} />
                    Accountability closed
                  </div>
                ) : (
                  <div className="text-[9.5px] mt-0.5 inline-flex items-center gap-1 font-extrabold text-amber-700">
                    <Clock size={9} strokeWidth={2.6} />
                    Pending accountability
                  </div>
                )}
              </div>
              <div className="text-right shrink-0">
                <div className="text-[13px] font-extrabold tabular num-hero text-slate-900 leading-none">
                  {d.amount}
                </div>
                <div className="text-[10px] text-slate-500 font-semibold mt-1 tabular">
                  {d.date}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
