"use client";

import { ChevronDown, Search, Star } from "lucide-react";
import { rvpCountryRequests, type RvpCountryRequest } from "@/lib/rvp-fund-approvals-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<RvpCountryRequest["status"], string> = {
  "Pending":       "bg-amber-100   text-amber-700",
  "Approved":      "bg-emerald-100 text-emerald-700",
  "Under Review":  "bg-sky-100     text-sky-700",
  "Draft":         "bg-slate-100   text-slate-600",
  "Overdue":       "bg-rose-100    text-rose-700",
  "No requests":   "bg-slate-50    text-slate-500",
};

// Left column — Country Fund Requests. Country picker list with flag
// emoji, lead name, amount, and status pill. The active country gets
// an emerald-ring focus state.
export function RvpCountryList() {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="mb-2.5">
        <h3 className="text-body-lg font-extrabold tracking-tight mb-2.5">Country Fund Requests</h3>
        <div className="flex items-center gap-2">
          <label className="flex-1 flex items-center gap-2 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white">
            <Search size={13} className="text-slate-400 shrink-0" />
            <input
              type="text"
              placeholder="Search countries…"
              className="bg-transparent outline-none flex-1 text-[12px] text-slate-700 placeholder:text-slate-400 min-w-0"
            />
          </label>
          <button
            type="button"
            className="inline-flex items-center gap-1 h-9 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700 transition-colors whitespace-nowrap"
          >
            <span className="muted">Sort:</span>
            <span>Priority</span>
            <ChevronDown size={11} className="text-slate-400" />
          </button>
        </div>
      </header>

      <ul className="flex flex-col gap-2">
        {rvpCountryRequests.map((c, i) => (
          <CountryRow
            key={c.id}
            c={c}
            stagger={["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7","stagger-8"][i] ?? ""}
          />
        ))}
      </ul>
    </article>
  );
}

function CountryRow({ c, stagger }: { c: RvpCountryRequest; stagger: string }) {
  return (
    <li
      className={cn(
        "rounded-xl border bg-white px-3 py-2.5 card-lift cursor-pointer tile-in flex items-center gap-3",
        stagger,
        c.isActive
          ? "border-blue-400 bg-blue-50/30 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.30),0_8px_24px_-8px_rgba(59,130,246,0.20)]"
          : "border-[var(--color-edify-border)]",
      )}
    >
      <span className="text-[22px] leading-none shrink-0" aria-hidden>{c.flag}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-body font-extrabold text-slate-900 truncate">{c.country}</span>
          {c.starred && <Star size={11} className="text-amber-500 fill-amber-500 shrink-0" />}
        </div>
        <div className="text-caption muted leading-tight mt-0.5 truncate">
          Lead: <span className="text-slate-700 font-semibold">{c.leadName}</span>
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        <span className="text-body font-extrabold tabular text-slate-900 num-hero">{c.amount}</span>
        <span className={cn(
          "inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
          STATUS_TONE[c.status],
        )}>
          {c.status}
          {typeof c.statusCount === "number" && (
            <span className="ml-1 opacity-80">({c.statusCount})</span>
          )}
        </span>
      </div>
    </li>
  );
}
