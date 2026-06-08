"use client";

import { Banknote, Coins, Receipt, Send, ShieldAlert, Wallet } from "lucide-react";
import {
  totalReceivedThisMonth,
  totalDisbursedThisMonth,
  totalAccountedThisMonth,
  totalOutstanding,
  totalAvailableBalance,
  pendingDisbursementQueue,
  pendingAccountabilityQueue,
} from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// 6 finance KPIs across the top of the Accountant disbursement console —
// one dense MetricStrip (the canonical app-wide KPI-row pattern).
export function AccountantKpiRow() {
  const pending = pendingDisbursementQueue();
  const pendingTotal = pending.reduce((a, r) => a + r.requestedAmount.amount, 0);
  const accountabilityCount = pendingAccountabilityQueue("STF-DM-014").length;

  const metrics: MetricCell[] = [
    { key: "available", label: "Funds Available", value: formatMoney(totalAvailableBalance), icon: Coins, tone: "good", delta: { dir: "up", text: "+UGX 90M top-up · across 2 treasury batches" } },
    { key: "pending", label: "Pending Disbursement", value: formatMoney({ amount: pendingTotal, currency: "UGX" }), icon: Send, tone: "alert", caption: `${pending.length} approved this week` },
    { key: "disbursed", label: "Disbursed This Month", value: formatMoney(totalDisbursedThisMonth), icon: Banknote, delta: { dir: "up", text: "+UGX 124M wk-3 · May 2026 cycle" } },
    { key: "accounted", label: "Accounted For", value: formatMoney(totalAccountedThisMonth), icon: Receipt, caption: "Receipts approved by Lead" },
    { key: "outstanding", label: "Outstanding in Field", value: formatMoney(totalOutstanding), icon: Wallet, tone: "alert", caption: `${accountabilityCount} accountabilities pending` },
    { key: "received", label: "Treasury Received", value: formatMoney(totalReceivedThisMonth), icon: ShieldAlert, caption: "RVP + HQ wires confirmed" },
  ];

  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
    </section>
  );
}
