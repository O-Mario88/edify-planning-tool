"use client";

import { ArrowUpRight, CheckCircle2, Clock, FileWarning, Send, Wallet } from "lucide-react";
import {
  pendingLeadQueue,
  pendingAccountabilityQueue,
  weeklyFundRequests,
} from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// 6 KPIs for the Lead's weekly-fund pipeline — one dense MetricStrip.
export function LeadWeeklyKpiRow() {
  const leadId = "STF-DM-014";
  const submittedCount = pendingLeadQueue(leadId).length;
  const submittedTotal = pendingLeadQueue(leadId).reduce((a, r) => a + r.requestedAmount.amount, 0);
  const approvedCount = weeklyFundRequests.filter((r) => r.programLeadId === leadId && r.status === "APPROVED").length;
  const disbursedCount = weeklyFundRequests.filter((r) => r.programLeadId === leadId && ["DISBURSED", "RECEIVED", "IN_USE"].includes(r.status)).length;
  const accountability = pendingAccountabilityQueue(leadId).length;
  const returned = weeklyFundRequests.filter((r) => r.programLeadId === leadId && ["RETURNED_TO_STAFF", "ACCOUNTABILITY_RETURNED"].includes(r.status)).length;
  const closed = weeklyFundRequests.filter((r) => r.programLeadId === leadId && r.status === "CLOSED").length;

  const metrics: MetricCell[] = [
    { key: "pending", label: "Pending Approval", value: submittedCount, icon: Clock, tone: "alert", caption: formatMoney({ amount: submittedTotal, currency: "UGX" }) },
    { key: "approved", label: "Approved · Awaiting Funds", value: approvedCount, icon: CheckCircle2, caption: "with Accountant" },
    { key: "disbursed", label: "Disbursed This Week", value: disbursedCount, icon: Send, tone: "good", caption: "in field" },
    { key: "accountability", label: "Accountability Pending", value: accountability, icon: FileWarning, caption: "receipts to review" },
    { key: "returned", label: "Returned", value: returned, icon: ArrowUpRight, tone: returned > 0 ? "alert" : "default", caption: "awaiting staff fix" },
    { key: "closed", label: "Closed This Month", value: closed, icon: Wallet, caption: "weeks fully accounted" },
  ];

  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
    </section>
  );
}
