"use client";

import { CheckCircle2, FileText, RotateCcw } from "lucide-react";
import { countryBudgetMix, countryRecentActivity, type CountryRecentActivity } from "@/lib/country-fund-approvals-mock";
import { cn } from "@/lib/utils";

const ACTION_ICON: Record<CountryRecentActivity["action"], { icon: typeof CheckCircle2; tone: string }> = {
  approved:      { icon: CheckCircle2, tone: "bg-emerald-100 text-emerald-700" },
  submitted:     { icon: FileText,     tone: "bg-sky-100     text-sky-700"     },
  returned:      { icon: RotateCcw,    tone: "bg-rose-100    text-rose-700"    },
  approved_prev: { icon: CheckCircle2, tone: "bg-emerald-50  text-emerald-600" },
};

// Both footer sections are exported individually so the page can
// promote Budget Mix to a full-width row and slot Recent Activity
// under the Fund Approval Queue.
export function CountryBudgetMixCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center gap-2 mb-2.5">
        <h3 className="text-[13px] font-extrabold tracking-tight">Approval Insights / Budget Mix</h3>
        <span className="text-[11px] muted font-semibold">(This Month)</span>
      </header>

      <div className="flex h-8 rounded-lg overflow-hidden shadow-[inset_0_1px_0_rgba(255,255,255,.5)]">
        {countryBudgetMix.map((s) => (
          <div
            key={s.key}
            className="grid place-items-center text-white text-caption font-extrabold tabular"
            style={{ width: `${s.pct}%`, backgroundColor: s.color }}
          >
            {s.pct}%
          </div>
        ))}
      </div>

      <ul className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2">
        {countryBudgetMix.map((s, i) => {
          const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7"][i] ?? "";
          return (
            <li key={s.key} className={cn("tile-in flex flex-col gap-0.5", stagger)}>
              <span className="inline-flex items-center gap-1.5 text-caption muted font-semibold leading-tight">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                <span className="truncate">{s.label}</span>
              </span>
              <span className="text-[12px] font-extrabold tabular text-slate-900 leading-tight num-hero">
                {s.amount}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="mt-2.5 text-caption muted leading-snug">
        All amounts are derived from planned activities and unit costs.
      </p>
    </article>
  );
}

export function CountryRecentActivityCard() {
  return (
    <article className="card p-3.5 flex flex-col" id="activity">
      <h3 className="text-[13px] font-extrabold tracking-tight mb-2">Recent Approval Activity</h3>
      <ul className="flex flex-col gap-1.5">
        {countryRecentActivity.map((a, i) => {
          const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4"][i] ?? "";
          const cfg = ACTION_ICON[a.action];
          const Icon = cfg.icon;
          return (
            <li
              key={a.id}
              className={cn(
                "rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 flex items-center gap-2.5 tile-in card-lift cursor-pointer",
                stagger,
              )}
            >
              <span className={cn("w-7 h-7 rounded-md grid place-items-center shrink-0", cfg.tone)}>
                <Icon size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[11.5px] font-extrabold text-slate-900 leading-tight">
                  <span className="text-slate-900">{a.who}</span>
                  <span className="muted font-semibold"> — {a.planLabel}</span>
                </div>
                <div className="text-[10px] muted leading-tight mt-0.5">{a.when}</div>
              </div>
              <span className="text-[11.5px] font-extrabold tabular text-slate-700 shrink-0 num-hero">{a.amount}</span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
