"use client";

import { ConsoleHeader } from "./ConsoleHeader";
import { ConsoleKpiStrip } from "./ConsoleKpiStrip";
import { BudgetApprovalsCard } from "./BudgetApprovalsCard";
import { DisbursementSummary } from "./DisbursementSummary";
import { DisbursementsByCategory } from "./DisbursementsByCategory";
import { DisbursementQueueTable } from "./DisbursementQueueTable";
import {
  AccountabilitySummary,
  TopOverdueAccountability,
} from "./AccountabilityCards";
import { ReceiptConfirmationTracker } from "./ReceiptConfirmationTracker";
import { ReimbursementQueue } from "./ReimbursementQueue";
import { BalanceReturnQueue } from "./BalanceReturnQueue";
import { FundsReceivedTable } from "./FundsReceivedTable";
import { RecentDisbursementsList } from "./RecentDisbursementsList";
import { QuickActionsGrid } from "./QuickActionsGrid";
import { AccountantPlanCard } from "@/components/planning/PlanCascadeCards";

// Program Accountant — full console dashboard.
//
// Grid packing strategy: pair tall content with tall, short with short.
// Quick Actions is the shortest widget so it becomes a horizontal action
// bar (no height-matching headache). Every other row uses `items-stretch`
// so left/right columns end at the same baseline.
//
//   Row 1  KPI strip (full)
//   Row 2  Budget (5) · Disb. Summary (4) · Donut (3)  — money story
//   Row 3  Queue (8) · Accountability + TopOverdue (4) — work surface
//   Row 4  Quick Actions horizontal strip              — 8 actions
//   Row 5  Funds Received (8) · Recent Disbursements (4) — inflow/outflow
export function AccountantConsoleDashboard() {
  return (
    <>
      <ConsoleHeader />
      <ConsoleKpiStrip />

      <div className="px-6 pb-6 space-y-4 lg:space-y-5">
        {/* Row 1b — budget auto-derived from the CCEO + PL field plans.
            This is where the money story originates. */}
        <AccountantPlanCard />

        {/* Row 2 — money story at a glance */}
        <section className="grid grid-cols-12 gap-4 lg:gap-5 items-stretch">
          <div className="col-span-12 xl:col-span-5">
            <BudgetApprovalsCard />
          </div>
          <div className="col-span-12 xl:col-span-4">
            <DisbursementSummary />
          </div>
          <div className="col-span-12 xl:col-span-3">
            <DisbursementsByCategory />
          </div>
        </section>

        {/* Row 3 — work surface + accountability */}
        <section className="grid grid-cols-12 gap-4 lg:gap-5 items-stretch">
          <div className="col-span-12 xl:col-span-8">
            <DisbursementQueueTable />
          </div>
          <div className="col-span-12 xl:col-span-4 flex flex-col gap-4 lg:gap-5">
            <AccountabilitySummary />
            <TopOverdueAccountability />
          </div>
        </section>

        {/* Row 4 — horizontal Quick Actions strip */}
        <section>
          <QuickActionsGrid />
        </section>

        {/* Row 5 — inflow / outflow */}
        <section className="grid grid-cols-12 gap-4 lg:gap-5 items-stretch">
          <div className="col-span-12 xl:col-span-8">
            <FundsReceivedTable />
          </div>
          <div className="col-span-12 xl:col-span-4">
            <RecentDisbursementsList />
          </div>
        </section>

        {/* ── Fund Accountability Operations ──────────────────────── */}
        <section className="pt-2">
          <div className="flex items-center gap-3 mb-3">
            <div className="h-px flex-1 bg-[#E5E9EE]" />
            <span className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-slate-400">
              Fund Accountability Operations
            </span>
            <div className="h-px flex-1 bg-[#E5E9EE]" />
          </div>
        </section>

        <section className="grid grid-cols-12 gap-4 lg:gap-5 items-stretch">
          <div className="col-span-12 xl:col-span-6">
            <ReceiptConfirmationTracker />
          </div>
          <div className="col-span-12 xl:col-span-6">
            <BalanceReturnQueue />
          </div>
        </section>

        <section className="grid grid-cols-12 gap-4 lg:gap-5 items-start">
          <div className="col-span-12">
            <ReimbursementQueue />
          </div>
        </section>
      </div>
    </>
  );
}
