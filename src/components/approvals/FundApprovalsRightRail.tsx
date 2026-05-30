"use client";

import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import {
  approvalRateThisMonth,
  approvalRules,
  monthlyAllocation,
  thisMonthSummary,
} from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";

// Right-rail summary cards — exported individually so the page can
// place Approval Rules under the Plan Detail and keep the 3 numeric
// summaries as a clean 3-up row.
export function FundApprovalsSummaryRow() {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 lg:gap-4 items-stretch">
      <ThisMonthCard />
      <AllocationCard />
      <ApprovalRateCard />
    </section>
  );
}

export function ThisMonthCard() {
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2.5">This Month</h3>
      <Row label="Waiting for Approval" value={thisMonthSummary.waitingForApproval} tone="amber" />
      <Row label="Returned"             value={thisMonthSummary.returned}           tone="rose"  />
      <Row label="Approved Today"       value={thisMonthSummary.approvedToday}      tone="emerald" />
      <a
        href="#activity"
        className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]"
      >
        View All activity
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "amber" | "rose" | "emerald";
}) {
  const cls = tone === "amber" ? "text-amber-700" : tone === "rose" ? "text-rose-700" : "text-emerald-700";
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-[#eef2f4] last:border-b-0">
      <span className="text-[11.5px] muted font-semibold">{label}</span>
      <span className={cn("text-body font-extrabold tabular num-hero", cls)}>{value}</span>
    </div>
  );
}

export function AllocationCard() {
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-[12px] font-extrabold tracking-tight">Monthly Plan & Budget Approval</h3>
        <span className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-emerald-100 text-emerald-700">
          {monthlyAllocation.status}
        </span>
      </header>
      <div className="flex items-center justify-between text-[11px]">
        <span className="muted font-semibold">Total Allocation</span>
        <span className="font-extrabold tabular text-slate-900 num-hero">{monthlyAllocation.totalAllocation}</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600"
          style={{ width: `${monthlyAllocation.approvedPct}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-caption">
        <span className="muted font-semibold">Approved (to date)</span>
        <span className="font-extrabold tabular text-emerald-700 num-hero">
          {monthlyAllocation.approvedToDate} <span className="muted font-semibold">({monthlyAllocation.approvedPct}%)</span>
        </span>
      </div>
      <a
        href="#dashboard"
        className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]"
      >
        View approval dashboard
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}

export function ApprovalRateCard() {
  const data = approvalRateThisMonth.segments.map((s) => ({ name: s.label, value: s.pct, color: s.color }));
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2">Approval Rate This Month</h3>
      <div className="flex items-center gap-4">
        <div className="relative w-[88px] h-[88px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={28} outerRadius={42} dataKey="value" paddingAngle={1} stroke="none">
                {data.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-[16px] font-extrabold tabular leading-none num-hero glow-emerald">
              {approvalRateThisMonth.rate}%
            </span>
            <span className="text-[8.5px] muted font-bold uppercase tracking-wide mt-0.5">Approval Rate</span>
          </div>
        </div>
        <ul className="flex-1 min-w-0 flex flex-col gap-1.5">
          {approvalRateThisMonth.segments.map((s) => (
            <li key={s.key} className="flex items-center gap-2 text-[11px]">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
              <span className="flex-1 muted font-semibold">{s.label}</span>
              <span className="font-extrabold tabular text-slate-700">{s.pct}%</span>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

export function ApprovalRulesCard() {
  return (
    <article className="card p-3.5 flex flex-col h-full">
      <h3 className="text-[12px] font-extrabold tracking-tight mb-2">Approval Rules</h3>
      <ul className="flex flex-col gap-1.5">
        {approvalRules.map((rule) => (
          <li key={rule} className="flex items-start gap-1.5 text-[11px] leading-snug">
            <ShieldCheck size={11} className="text-emerald-600 shrink-0 mt-0.5" />
            <span className="text-slate-700 font-semibold">{rule}</span>
          </li>
        ))}
      </ul>
      <a
        href="#guidelines"
        className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]"
      >
        View full approval guidelines
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}
