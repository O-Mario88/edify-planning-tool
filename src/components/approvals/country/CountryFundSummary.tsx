"use client";

import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import {
  countryApprovalRate,
  countryPlanBudget,
  countryThisMonth,
} from "@/lib/country-fund-approvals-mock";
import { approvalRules } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";

// 3-card summary row + Approval Rules card. CD-specific numbers.
export function CountryFundSummaryRow() {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 lg:gap-4 items-stretch">
      <ThisMonthCard />
      <CountryAllocationCard />
      <ApprovalRateCard />
    </section>
  );
}

function ThisMonthCard() {
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2.5">This Month</h3>
      <Row label="Waiting for Approval" value={countryThisMonth.waitingForApproval} tone="amber" />
      <Row label="Returned for Review"  value={countryThisMonth.returned}           tone="rose"  />
      <Row label="Approved Today"       value={countryThisMonth.approvedToday}      tone="emerald" />
      <a href="#activity" className="mt-auto pt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
        View All activity
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone: "amber" | "rose" | "emerald" }) {
  const cls = tone === "amber" ? "text-amber-700" : tone === "rose" ? "text-rose-700" : "text-emerald-700";
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-[#eef2f4] last:border-b-0">
      <span className="text-[11.5px] muted font-semibold">{label}</span>
      <span className={cn("text-body font-extrabold tabular num-hero", cls)}>{value}</span>
    </div>
  );
}

function CountryAllocationCard() {
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <header className="mb-2">
        <h3 className="text-[12px] font-extrabold tracking-tight">Country Plan & Budget Approval</h3>
      </header>
      <div className="flex items-center justify-between text-[11px]">
        <span className="muted font-semibold">Total Allocation</span>
        <span className="font-extrabold tabular text-slate-900 num-hero">{countryPlanBudget.totalAllocation}</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600"
             style={{ width: `${countryPlanBudget.approvedPct}%` }} />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-caption">
        <span className="muted font-semibold">Approved (to date)</span>
        <span className="font-extrabold tabular text-emerald-700 num-hero">
          {countryPlanBudget.approvedToDate} <span className="muted font-semibold">({countryPlanBudget.approvedPct}%)</span>
        </span>
      </div>
      <a href="#country-budget" className="mt-auto pt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
        View Plan & budget
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}

function ApprovalRateCard() {
  const data = countryApprovalRate.segments.map((s) => ({ name: s.label, value: s.pct, color: s.color }));
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2">Approval Rate This Month</h3>
      <div className="flex items-center gap-4 flex-1">
        <div className="relative w-[88px] h-[88px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={28} outerRadius={42} dataKey="value" paddingAngle={1} stroke="none">
                {data.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 grid place-items-center pointer-events-none">
            <span className="text-[19px] font-extrabold tabular leading-none num-hero glow-emerald text-[var(--color-edify-text)]">{countryApprovalRate.rate}%</span>
          </div>
        </div>
        <ul className="flex-1 min-w-0 flex flex-col gap-1.5">
          {countryApprovalRate.segments.map((s) => (
            <li key={s.key} className="flex items-center gap-2 text-[11px]">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
              <span className="flex-1 muted font-semibold">{s.label}</span>
              <span className="font-extrabold tabular text-slate-700">{s.pct}%</span>
            </li>
          ))}
        </ul>
      </div>
      <a href="#analytics" className="mt-2 pt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
        View full analytics
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}

export function CountryApprovalRulesCard() {
  return (
    <article className="card p-3.5 flex flex-col">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2">Approval Rules</h3>
      <ul className="flex flex-col gap-1.5">
        {approvalRules.map((rule) => (
          <li key={rule} className="flex items-start gap-1.5 text-[11px] leading-snug">
            <ShieldCheck size={11} className="text-emerald-600 shrink-0 mt-0.5" />
            <span className="text-slate-700 font-semibold">{rule}</span>
          </li>
        ))}
      </ul>
      <a href="#guidelines" className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
        View full approval guidelines
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}
