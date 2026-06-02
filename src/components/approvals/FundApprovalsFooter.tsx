"use client";

import { ArrowUpRight, CheckCircle2, RotateCcw } from "lucide-react";
import { budgetMixThisMonth, recentApprovalActivity } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";
import { readableInk } from "@/lib/color";

// Footer row — Approval Insights / Budget Mix (left, wider) + Recent
// Approval Activity (right, narrower).
export function FundApprovalsFooter() {
  return (
    <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
      <div className="col-span-12 lg:col-span-7">
        <BudgetMixCard />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <RecentActivityCard />
      </div>
    </section>
  );
}

function BudgetMixCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center gap-2 mb-2.5">
        <h3 className="text-[13px] font-extrabold tracking-tight">Approval Insights / Budget Mix</h3>
        <span className="text-[11px] muted font-semibold">(This Month)</span>
      </header>

      {/* Stacked horizontal bar — one segment per category. */}
      <div className="flex h-8 rounded-lg overflow-hidden shadow-[inset_0_1px_0_rgba(255,255,255,.5)]">
        {budgetMixThisMonth.map((s) => (
          <div
            key={s.key}
            className="grid place-items-center text-caption font-extrabold tabular"
            style={{ width: `${s.pct}%`, backgroundColor: s.color, color: readableInk(s.color) }}
          >
            {s.pct}%
          </div>
        ))}
      </div>

      {/* Legend — 6 chips with dot + label + amount, each tile-in for
          a subtle staggered entrance. */}
      <ul className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {budgetMixThisMonth.map((s, i) => {
          const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <li
              key={s.key}
              className={cn("tile-in flex flex-col gap-0.5", stagger)}
            >
              <span className="inline-flex items-center gap-1.5 text-caption muted font-semibold leading-tight">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                <span className="truncate">{s.label}</span>
              </span>
              <span className="text-[12px] font-extrabold tabular text-[var(--color-edify-text)] leading-tight num-hero">
                {s.amount}
              </span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function RecentActivityCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col" id="activity">
      <h3 className="text-[13px] font-extrabold tracking-tight mb-2">Recent Approval Activity</h3>
      <ul className="flex flex-col gap-1.5">
        {recentApprovalActivity.map((a, i) => {
          const stagger = ["stagger-1","stagger-2","stagger-3"][i] ?? "";
          const isReturn = a.action === "returned";
          const Icon = isReturn ? RotateCcw : CheckCircle2;
          return (
            <li
              key={a.id}
              className={cn(
                "rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 flex items-center gap-2.5 tile-in card-lift cursor-pointer",
                stagger,
              )}
            >
              <span className={cn(
                "w-7 h-7 rounded-md grid place-items-center shrink-0",
                isReturn ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700",
              )}>
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
      <a
        href="#activity-all"
        className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]"
      >
        View All activity
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}
