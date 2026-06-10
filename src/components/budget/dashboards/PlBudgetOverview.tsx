"use client";

// PL Budget Overview — operational budget only (excludes admin/overhead).
// Tracks budgets from CCEO plans, PL-led plans, and special projects.

import { useState } from "react";
import {
  Shield, FileText, Rocket, Send, ArrowUp, Wallet, Flame, Download, BarChart3, Info, MapPin,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { BudgetKpiRow, type BudgetKpi } from "../BudgetKpiRow";
import { ApprovalWorkflowStepper, type WorkflowStep } from "../ApprovalWorkflowStepper";
import { BudgetHealthGauge } from "../BudgetHealthGauge";
import { AnnualOverviewLines, BudgetByQuarterBars, MonthlyBurnReleases, BudgetMixDonut, BudgetByDimensionBars } from "../BudgetCharts";
import { BudgetRiskAlerts, BudgetSnapshots, SectionEyebrow } from "../BudgetCards";
import { fmtUgxShort, fmtPct } from "@/lib/funds/budget/budget-format";
import type { AnnualBudgetRollup } from "@/lib/funds/budget/annual-rollup";
import type { OperationalTotals } from "@/lib/funds/budget/budget-summary";

const TABS = ["Annual Summary", "Quarterly Summary", "Monthly Summary", "Fund Requests"] as const;
type Tab = (typeof TABS)[number];

const STEPS: WorkflowStep[] = [
  { label: "CCEO / PL Submission", status: "done", date: "Apr 20, 2026" },
  { label: "PL Review", status: "current", date: "Apr 24, 2026", statusLabel: "In Progress" },
  { label: "IA Review", status: "pending", date: "Apr 27, 2026" },
  { label: "Accountant Review", status: "pending", date: "Apr 30, 2026" },
  { label: "CD Approval", status: "pending", date: "May 3, 2026" },
  { label: "RVP Approval", status: "pending", date: "May 6, 2026" },
];

export function PlBudgetOverview({ rollup, operational }: { rollup: AnnualBudgetRollup; operational: OperationalTotals }) {
  const [tab, setTab] = useState<Tab>("Annual Summary");
  const mix = operational.mixBySource;
  const find = (k: string) => mix.find((m) => m.key === k)?.amount ?? 0;

  const kpis: BudgetKpi[] = [
    { key: "total", label: "Total Operational Budget", value: fmtUgxShort(operational.approved), caption: "Across all operational plans", delta: "8.4%", deltaTone: "up", Icon: Shield, tone: "bg-emerald-50 text-emerald-700", hero: true },
    { key: "cceo", label: "CCEO Planned Budget", value: fmtUgxShort(find("cceo")), caption: "From CCEO staff plans", delta: "9.1%", deltaTone: "up", Icon: FileText, tone: "bg-blue-50 text-blue-700" },
    { key: "pl", label: "PL Planned Budget", value: fmtUgxShort(find("pl")), caption: "From PL-led plans", delta: "6.7%", deltaTone: "up", Icon: MapPin, tone: "bg-violet-50 text-violet-700" },
    { key: "proj", label: "Special Project Budget", value: fmtUgxShort(find("project")), caption: "From special projects", delta: "7.3%", deltaTone: "up", Icon: Rocket, tone: "bg-orange-50 text-orange-700" },
    { key: "requested", label: "Requested Funds", value: fmtUgxShort(operational.requested), caption: "Total fund requests", delta: "11.2%", deltaTone: "up", Icon: Send, tone: "bg-sky-50 text-sky-700" },
    { key: "released", label: "Released Funds", value: fmtUgxShort(operational.released), caption: "Funds released", delta: "8.6%", deltaTone: "up", Icon: ArrowUp, tone: "bg-blue-50 text-blue-700", hero: true },
    { key: "remaining", label: "Remaining Balance", value: fmtUgxShort(operational.remaining), caption: "Unspent balance", delta: "4.8%", deltaTone: "down", Icon: Wallet, tone: "bg-teal-50 text-teal-700", hero: true },
    { key: "burn", label: "Current Month Burn", value: fmtUgxShort(operational.spent / 8), caption: "Burn this month", delta: "7.1%", deltaTone: "up", Icon: Flame, tone: "bg-orange-50 text-orange-700", hero: true },
  ];

  const stepsDone = STEPS.filter((s) => s.status === "done").length;
  const currentStep = STEPS.find((s) => s.status === "current");
  const stagePct = Math.round((stepsDone / STEPS.length) * 100);

  const ratio = rollup.released ? operational.released / rollup.released : 1;
  let relCum = 0;
  const overview = rollup.byMonth.map((m, i) => {
    relCum += m.released * ratio;
    const approvedCum = (operational.approved / 12) * (i + 1);
    return {
      label: m.label,
      approved: Math.round(approvedCum),
      requested: Math.min(operational.approved, Math.round(relCum / 0.7)),
      released: Math.round(relCum),
      remaining: Math.max(0, Math.round(approvedCum - relCum)),
    };
  });

  return (
    <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
      {/* Toolbar — tabs left, actions right. The page title lives in the
          canonical <PageHeader> mounted by /budget/page.tsx, so this row was
          demoted from a header to an action toolbar (no duplicate title). */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50 w-fit">
          {TABS.map((t) => (
            <button key={t} type="button" onClick={() => setTab(t)}
              className={`h-8 px-3 rounded-md text-[12px] font-bold transition-colors ${tab === t ? "bg-[var(--color-edify-primary)] text-white" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"}`}>
              {t}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold">{rollup.fyLabel}</span>
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold inline-flex items-center gap-1.5"><Download size={13} /> Export</span>
          <span className="h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold inline-flex items-center gap-1.5"><Shield size={14} /> Review Budget Requests</span>
        </div>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800 inline-flex items-center gap-1.5">
        <Info size={13} /> Operational budget only — excludes admin budget and overhead costs.
      </div>

      <BudgetKpiRow items={kpis} />

      <SectionEyebrow>Approval &amp; Status</SectionEyebrow>

      <section className="grid grid-cols-12 gap-4 items-stretch">
        <div className="col-span-12 lg:col-span-8">
          <SectionCard title="Plan & Budget Approval Workflow">
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
          <SectionCard title="PL Review Status">
            <div className="grid grid-cols-2 gap-3 text-center">
              <div className="rounded-lg border border-[var(--color-edify-border)] p-3"><div className="text-[18px] font-extrabold text-orange-600">{rollup.pendingFundRequests.count}</div><div className="text-[10.5px] muted">Pending Items</div></div>
              <div className="rounded-lg border border-[var(--color-edify-border)] p-3"><div className="text-[18px] font-extrabold">2.3 days</div><div className="text-[10.5px] muted">Avg. Review Time</div></div>
            </div>
            <p className="text-[11px] muted mt-2">You review field budgets before they move to finance approval.</p>
          </SectionCard>
        </div>
      </section>

      <SectionEyebrow>Budget Performance</SectionEyebrow>

      {/* Operational trend (wide) + health gauge — 2-up. */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-8"><SectionCard title="Annual Operational Budget Trend (UGX)"><AnnualOverviewLines data={overview} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-4"><SectionCard title="Operational Budget Health"><BudgetHealthGauge score={rollup.healthScore} split={rollup.healthSplit} /></SectionCard></div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-6"><SectionCard title="Quarterly Budget Performance (UGX)"><BudgetByQuarterBars data={rollup.byQuarter} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-6"><SectionCard title="Monthly Burn & Releases (UGX)"><MonthlyBurnReleases data={rollup.byMonth} /></SectionCard></div>
      </section>

      <SectionEyebrow>Regional Allocation</SectionEyebrow>

      {/* Region bars (wide) + a compact rail (budget mix by source + risk). */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 lg:col-span-8"><SectionCard title="Budget by Region (by Approved Budget)"><BudgetByDimensionBars data={rollup.byRegion} height={320} /></SectionCard></div>
        <div className="col-span-12 lg:col-span-4 space-y-4">
          <SectionCard title="Budget Mix by Source"><BudgetMixDonut data={mix} centerPct="100%" centerLabel="Operational" /></SectionCard>
          <BudgetRiskAlerts alerts={rollup.riskAlerts} title="Budget Risk Alerts" />
        </div>
      </section>

      <BudgetSnapshots rollup={rollup} />
    </div>
  );
}
