"use client";

// Annual Budget dashboard — shared by Country Director, Accountant, and Impact
// Assessment. Budget is generated from the annual plan; this is the full
// summary + detailed (ledger) view.

import { useState } from "react";
import {
  Lock, Shield, FileText, Flame, Scale, BarChart3, Download, Send, Wallet, UserRound, ClipboardCheck,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { BudgetKpiRow, type BudgetKpi } from "../BudgetKpiRow";
import { ApprovalWorkflowStepper, type WorkflowStep } from "../ApprovalWorkflowStepper";
import { BudgetHealthGauge } from "../BudgetHealthGauge";
import { BudgetByQuarterBars, MonthlyBurnReleases, BudgetByDimensionBars, ProgramAdminDonut } from "../BudgetCharts";
import { BudgetRiskAlerts, FundRequestStatusRow, RecentFundRequestsCard, type RecentFundRequest } from "../BudgetCards";
import { BudgetLedgerTable } from "../BudgetLedgerTable";
import { fmtUgxShort, fmtPct } from "@/lib/funds/budget/budget-format";
import type { AnnualBudgetRollup } from "@/lib/funds/budget/annual-rollup";

const TABS = ["Annual Summary", "Annual Detailed", "Quarterly", "Monthly", "Fund Requests"] as const;
type Tab = (typeof TABS)[number];

const STEPS: WorkflowStep[] = [
  { label: "CEO / Staff Submission", status: "done", date: "Apr 25, 2026" },
  { label: "PL Review", status: "done", date: "Apr 28, 2026" },
  { label: "IA Review", status: "done", date: "Apr 30, 2026" },
  { label: "Accountant Review", status: "current", date: "May 1, 2026", statusLabel: "In Progress" },
  { label: "CD Approval", status: "pending" },
  { label: "RVP Approval", status: "pending" },
];

export function AnnualBudgetDashboard({ rollup }: { rollup: AnnualBudgetRollup }) {
  const [tab, setTab] = useState<Tab>("Annual Summary");

  const kpis: BudgetKpi[] = [
    { key: "total", label: "FY Total Budget", value: fmtUgxShort(rollup.fyTotalBudget), caption: "Total approved plan", delta: "8.7%", deltaTone: "up", Icon: Lock },
    { key: "approved", label: "Approved Budget", value: fmtUgxShort(rollup.approved), caption: "For implementation", delta: "8.1%", deltaTone: "up", Icon: Shield, tone: "bg-emerald-50 text-emerald-700", hero: true },
    { key: "requested", label: "Requested Funds", value: fmtUgxShort(rollup.requested), caption: "Cumulative requests", delta: "12.4%", deltaTone: "up", Icon: FileText, tone: "bg-blue-50 text-blue-700" },
    { key: "released", label: "Released Funds", value: fmtUgxShort(rollup.released), caption: "Funds disbursed", delta: "9.3%", deltaTone: "up", Icon: Send, tone: "bg-orange-50 text-orange-700", hero: true },
    { key: "remaining", label: "Remaining Balance", value: fmtUgxShort(rollup.remaining), caption: "Unspent balance", delta: "5.6%", deltaTone: "up", Icon: Scale, tone: "bg-teal-50 text-teal-700", hero: true },
    { key: "burn", label: "Burn Rate", value: fmtPct(rollup.burnRatePct), caption: "Spend vs approved", delta: "3.2 pp", deltaTone: "up", Icon: Flame, tone: "bg-rose-50 text-rose-700", hero: true },
    { key: "util", label: "Budget Utilization", value: fmtPct(rollup.utilizationPct), caption: "Utilization rate", delta: "3.6 pp", deltaTone: "up", Icon: BarChart3, tone: "bg-emerald-50 text-emerald-700" },
    { key: "pending", label: "Pending Fund Requests", value: fmtUgxShort(rollup.pendingFundRequests.amount), caption: `${rollup.pendingFundRequests.count} requests`, Icon: UserRound, tone: "bg-violet-50 text-violet-700" },
  ];

  const recent: RecentFundRequest[] = rollup.ledger
    .filter((r) => r.fundRequestStatus === "Under Review" || r.fundRequestStatus === "Approved" || r.fundRequestStatus === "Released")
    .slice(0, 5)
    .map((r, i) => ({
      id: `FRQ-2026-0${147 - i}`,
      name: r.staff ?? r.partner ?? "Field team",
      region: r.region === "—" ? r.district : r.region,
      status: r.fundRequestStatus,
      date: `${r.monthLabel} ${r.week * 6}`,
      tone: r.fundRequestStatus === "Approved" ? "green" : r.fundRequestStatus === "Released" ? "blue" : "amber",
    }));

  const programPct = rollup.fyTotalBudget ? Math.round((rollup.programCost / rollup.fyTotalBudget) * 1000) / 10 : 0;

  const stepsDone = STEPS.filter((s) => s.status === "done").length;
  const currentStep = STEPS.find((s) => s.status === "current");
  const stagePct = Math.round((stepsDone / STEPS.length) * 100);

  return (
    <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap pt-2">
        <div>
          <h1 className="text-[22px] font-extrabold tracking-tight">Annual Budget</h1>
          <p className="text-[12px] muted">Monitor approved budgets, quarterly allocations, monthly burn, and fund requests.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold inline-flex items-center gap-1.5">{rollup.fyLabel}</span>
          <span className="h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold inline-flex items-center gap-1.5"><Download size={13} /> Export</span>
          <span className="h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold inline-flex items-center gap-1.5"><ClipboardCheck size={14} /> Submit for Approval</span>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50 w-fit">
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`h-8 px-3 rounded-md text-[12px] font-bold transition-colors ${tab === t ? "bg-[var(--color-edify-primary)] text-white" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"}`}>
            {t}
          </button>
        ))}
      </div>

      <BudgetKpiRow items={kpis} />

      {/* Workflow + recent requests */}
      <section className="grid grid-cols-12 gap-4 items-stretch">
        <div className="col-span-12 lg:col-span-8">
          <SectionCard icon={<ClipboardCheck size={13} />} title="Budget & Fund Approval Workflow">
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
          <RecentFundRequestsCard requests={recent} />
        </div>
      </section>

      {tab === "Annual Detailed" || tab === "Fund Requests" ? (
        <BudgetLedgerTable rows={rollup.ledger} />
      ) : (
        <>
          {/* Charts */}
          {/* Time-series charts — 2-up so the 12-month + quarterly series get
              room to breathe (no squeezed 3-up). */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 lg:col-span-6">
              <SectionCard title="Budget by Quarter (UGX)"><BudgetByQuarterBars data={rollup.byQuarter} /></SectionCard>
            </div>
            <div className="col-span-12 lg:col-span-6">
              <SectionCard title="Monthly Burn & Releases (UGX)"><MonthlyBurnReleases data={rollup.byMonth} /></SectionCard>
            </div>
          </section>

          {/* District bars (wide) + a compact rail (cost mix + health). */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 lg:col-span-8">
              <SectionCard title="Budget by District (Top 8) (UGX)"><BudgetByDimensionBars data={rollup.byDistrict} height={320} /></SectionCard>
            </div>
            <div className="col-span-12 lg:col-span-4 space-y-4">
              <SectionCard title="Program vs Admin Cost (UGX)">
                <ProgramAdminDonut program={rollup.programCost} admin={rollup.adminCost} centerPct={`${programPct}%`} centerLabel="Program Cost" />
                <div className="mt-2 space-y-1 text-[11.5px]">
                  <div className="flex items-center justify-between"><span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: "#1f4d3a" }} />Program</span><b>{fmtUgxShort(rollup.programCost)}</b></div>
                  <div className="flex items-center justify-between"><span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: "#ea8c2f" }} />Admin</span><b>{fmtUgxShort(rollup.adminCost)}</b></div>
                </div>
              </SectionCard>
              <SectionCard title="Budget Health"><BudgetHealthGauge score={rollup.healthScore} split={rollup.healthSplit} /></SectionCard>
            </div>
          </section>

          {/* Fund-request status (wide strip) + risk alerts. */}
          <section className="grid grid-cols-12 gap-4 items-start">
            <div className="col-span-12 lg:col-span-8">
              <FundRequestStatusRow counts={rollup.fundRequestStatusCounts} />
            </div>
            <div className="col-span-12 lg:col-span-4">
              <BudgetRiskAlerts alerts={rollup.riskAlerts} />
            </div>
          </section>

          {tab !== "Annual Summary" && <BudgetLedgerTable rows={rollup.ledger} />}
        </>
      )}
    </div>
  );
}
