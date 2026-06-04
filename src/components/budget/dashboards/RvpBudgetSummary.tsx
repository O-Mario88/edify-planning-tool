"use client";

// RVP Budget Summary — executive, summary-only (no raw activity ledger). The
// RVP gives final approval; sees annual/quarterly/monthly rollups + risk.

import { useState } from "react";
import {
  Shield, FileText, Send, Wallet, Flame, Clock, Download, BarChart3, AlertTriangle,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { BudgetKpiRow, type BudgetKpi } from "../BudgetKpiRow";
import { ApprovalWorkflowStepper, type WorkflowStep } from "../ApprovalWorkflowStepper";
import { BudgetHealthGauge } from "../BudgetHealthGauge";
import { AnnualOverviewLines, BudgetByQuarterBars, MonthlyBurnReleases, ProgramAdminDonut, BudgetByDimensionBars } from "../BudgetCharts";
import { BudgetRiskAlerts, BudgetSnapshots } from "../BudgetCards";
import { fmtUgxShort, fmtPct } from "@/lib/funds/budget/budget-format";
import type { AnnualBudgetRollup } from "@/lib/funds/budget/annual-rollup";

const TABS = ["Annual Summary", "Quarterly Summary", "Monthly Summary"] as const;
type Tab = (typeof TABS)[number];

const STEPS: WorkflowStep[] = [
  { label: "Staff / CCEO Submission", status: "done", date: "Apr 20, 2026" },
  { label: "PL Review", status: "done", date: "Apr 23, 2026" },
  { label: "IA Review", status: "done", date: "Apr 25, 2026" },
  { label: "Accountant Review", status: "done", date: "Apr 28, 2026" },
  { label: "CD Approval", status: "done", date: "May 2, 2026" },
  { label: "RVP Final Approval", status: "current", statusLabel: "Awaiting your decision" },
];

export function RvpBudgetSummary({ rollup }: { rollup: AnnualBudgetRollup }) {
  const [tab, setTab] = useState<Tab>("Annual Summary");

  const kpis: BudgetKpi[] = [
    { key: "approved", label: "Annual Approved Budget", value: fmtUgxShort(rollup.approved), caption: "Total approved budget", delta: "8.7%", deltaTone: "up", Icon: Shield, tone: "bg-emerald-50 text-emerald-700", hero: true },
    { key: "requested", label: "Annual Requested Funds", value: fmtUgxShort(rollup.requested), caption: "Total requested", delta: "9.2%", deltaTone: "up", Icon: FileText, tone: "bg-blue-50 text-blue-700" },
    { key: "released", label: "Annual Released Funds", value: fmtUgxShort(rollup.released), caption: "Total released", delta: "12.6%", deltaTone: "up", Icon: Send, tone: "bg-violet-50 text-violet-700", hero: true },
    { key: "remaining", label: "Remaining Annual Balance", value: fmtUgxShort(rollup.remaining), caption: "Unspent balance", delta: "5.4%", deltaTone: "down", Icon: Wallet, tone: "bg-teal-50 text-teal-700", hero: true },
    { key: "burn", label: "Burn Rate", value: fmtPct(rollup.burnRatePct), caption: "Spend vs approved", delta: "3.2 pp", deltaTone: "up", Icon: Flame, tone: "bg-rose-50 text-rose-700", hero: true },
    { key: "util", label: "Budget Utilization", value: fmtPct(rollup.utilizationPct), caption: "Released vs approved", delta: "3.6 pp", deltaTone: "up", Icon: BarChart3, tone: "bg-emerald-50 text-emerald-700" },
    { key: "spent", label: "Current Month Burn", value: fmtUgxShort(rollup.spent / 8), caption: "Burn this month", delta: "7.3%", deltaTone: "up", Icon: Flame, tone: "bg-orange-50 text-orange-700" },
    { key: "pending", label: "Pending Final Approvals", value: String(rollup.pendingFundRequests.count), caption: "Awaiting your approval", Icon: Clock, tone: "bg-amber-50 text-amber-700" },
  ];

  // Cumulative annual overview from the live monthly series.
  let relCum = 0;
  const overview = rollup.byMonth.map((m) => {
    relCum += m.released;
    const approvedCum = m.runRate;
    return {
      label: m.label,
      approved: approvedCum,
      requested: Math.min(rollup.approved, Math.round(relCum / 0.7)),
      released: relCum,
      remaining: Math.max(0, approvedCum - relCum),
    };
  });

  const programPct = rollup.fyTotalBudget ? Math.round((rollup.programCost / rollup.fyTotalBudget) * 1000) / 10 : 0;

  const stepsDone = STEPS.filter((s) => s.status === "done").length;
  const currentStep = STEPS.find((s) => s.status === "current");
  const stagePct = Math.round((stepsDone / STEPS.length) * 100);

  return (
    <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
      <header className="flex items-start justify-between gap-3 flex-wrap pt-2">
        <div>
          <h1 className="text-[22px] font-extrabold tracking-tight">RVP Budget Summary</h1>
          <p className="text-[12px] muted">Executive summary of annual, quarterly, and monthly budgets, approvals, and fund performance.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold">{rollup.fyLabel}</span>
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold inline-flex items-center gap-1.5"><Download size={13} /> Export</span>
          <span className="h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold inline-flex items-center gap-1.5"><Shield size={14} /> Final Approval Review</span>
        </div>
      </header>

      <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50 w-fit">
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`h-8 px-3 rounded-md text-[12px] font-bold transition-colors ${tab === t ? "bg-[var(--color-edify-primary)] text-white" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"}`}>
            {t}
          </button>
        ))}
      </div>

      <BudgetKpiRow items={kpis} />

      <section className="grid grid-cols-12 gap-4 items-stretch">
        <div className="col-span-12 lg:col-span-8">
          <SectionCard title="Budget Approval Workflow">
            <div className="flex-1 flex items-center"><ApprovalWorkflowStepper steps={STEPS} /></div>
            <div className="pt-3 space-y-2">
              <div className="h-1.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
                <div className="h-full rounded-full bg-[var(--color-edify-primary)] transition-all" style={{ width: `${stagePct}%` }} />
              </div>
              <div className="flex items-center justify-between gap-3 text-[11px]">
                <span className="muted">
                  Current stage: <b style={{ color: "var(--color-edify-orange,#ea8c2f)" }}>{currentStep?.label ?? "Complete"}</b>
                  {currentStep?.statusLabel ? ` · ${currentStep.statusLabel}` : ""}
                </span>
                <span className="muted font-semibold tabular">{stepsDone} of {STEPS.length} stages complete</span>
              </div>
            </div>
          </SectionCard>
        </div>
        <div className="col-span-12 lg:col-span-4">
          <SectionCard title="RVP Approval Status" actions={<StatusBadge tone="amber">In Progress</StatusBadge>}>
            <div className="grid grid-cols-2 gap-3 text-center">
              <div className="rounded-lg border border-[var(--color-edify-border)] p-3"><Clock size={15} className="mx-auto text-[var(--color-edify-primary)]" /><div className="text-[18px] font-extrabold mt-1">2.4 days</div><div className="text-[10.5px] muted">Avg. Review Time</div></div>
              <div className="rounded-lg border border-[var(--color-edify-border)] p-3"><FileText size={15} className="mx-auto text-[var(--color-edify-primary)]" /><div className="text-[18px] font-extrabold mt-1">{rollup.pendingFundRequests.count}</div><div className="text-[10.5px] muted">Pending Items</div></div>
            </div>
            <p className="text-[11px] muted mt-2">Your approval is the final step in the workflow.</p>
          </SectionCard>
        </div>
      </section>

      {/* Overview trend (wide) + health gauge — 2-up. */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-8"><SectionCard title="Annual Budget Overview (UGX)"><AnnualOverviewLines data={overview} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-4"><SectionCard title="Annual Budget Health"><BudgetHealthGauge score={rollup.healthScore} split={rollup.healthSplit} /></SectionCard></div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-6"><SectionCard title="Quarterly Budget Performance (UGX)"><BudgetByQuarterBars data={rollup.byQuarter} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-6"><SectionCard title="Monthly Burn & Releases (UGX)"><MonthlyBurnReleases data={rollup.byMonth} /></SectionCard></div>
      </section>

      {/* Regional bars (wide) + a compact rail (budget mix + risk). */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-8"><SectionCard title="Regional Budget Health (by Approved Budget)"><BudgetByDimensionBars data={rollup.byRegion} height={320} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-4 space-y-4">
          <SectionCard title="Annual Budget Mix"><ProgramAdminDonut program={rollup.programCost} admin={rollup.adminCost} centerPct={`${programPct}%`} centerLabel="Program Cost" /></SectionCard>
          <BudgetRiskAlerts alerts={rollup.riskAlerts} title="Budget Risk Alerts" />
        </div>
      </section>

      <BudgetSnapshots rollup={rollup} />
    </div>
  );
}
