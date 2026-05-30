"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { countryFundQueue, type CountryFundQueueItem } from "@/lib/country-fund-approvals-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CountryFundQueueItem["status"], string> = {
  "Awaiting Approval": "bg-amber-100 text-amber-700",
  "Returned":          "bg-rose-100  text-rose-700",
};

export function CountryFundQueue() {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-body-lg font-extrabold tracking-tight">Fund Approval Queue</h3>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-slate-100 text-caption font-extrabold tabular text-slate-700">
            {countryFundQueue.length}
          </span>
        </div>
        <button type="button" className="inline-flex items-center gap-1 text-[11.5px] font-semibold muted whitespace-nowrap">
          Sort by: <span className="text-slate-700 font-bold">Amount</span>
        </button>
      </header>

      <ul className="flex flex-col gap-2 flex-1">
        {countryFundQueue.map((q, i) => (
          <QueueRow key={q.id} q={q} stagger={["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7"][i] ?? ""} />
        ))}
      </ul>

      <footer className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[11px] muted">
        <span>Showing 1–{countryFundQueue.length} of {countryFundQueue.length} leads</span>
        <div className="flex items-center gap-1">
          <button type="button" disabled className="w-6 h-6 rounded-md border border-[var(--color-edify-border)] grid place-items-center disabled:opacity-40">
            <ChevronLeft size={12} />
          </button>
          <button type="button" disabled className="w-6 h-6 rounded-md border border-[var(--color-edify-border)] grid place-items-center disabled:opacity-40">
            <ChevronRight size={12} />
          </button>
        </div>
      </footer>
    </article>
  );
}

function QueueRow({ q, stagger }: { q: CountryFundQueueItem; stagger: string }) {
  return (
    <li
      className={cn(
        "rounded-xl border bg-white p-3 card-lift cursor-pointer tile-in flex items-center gap-3",
        stagger,
        q.isActive
          ? "border-emerald-400 bg-emerald-50/40 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.35),0_8px_24px_-8px_rgba(16,185,129,0.20)]"
          : "border-[var(--color-edify-border)]",
      )}
    >
      <span className={cn(
        "w-10 h-10 rounded-full grid place-items-center text-[12px] font-extrabold text-white shrink-0 shadow-sm",
        q.isActive
          ? "bg-gradient-to-br from-emerald-500 to-emerald-700"
          : "bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]",
      )}>
        {q.initials}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-body font-extrabold text-slate-900 truncate">{q.leadName}</div>
        <div className="text-caption muted leading-tight mt-0.5 truncate">{q.region}</div>
        <div className="text-caption muted leading-tight truncate">{q.planLabel}</div>
      </div>
      <div className="flex flex-col items-end gap-1.5 shrink-0">
        <span className={cn(
          "inline-flex items-center px-2 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
          STATUS_TONE[q.status],
        )}>
          {q.status}
        </span>
        <span className="text-body-lg font-extrabold tabular text-slate-900 num-hero">{q.amount}</span>
      </div>
      <ChevronRight size={14} className="text-slate-300 shrink-0" />
    </li>
  );
}
