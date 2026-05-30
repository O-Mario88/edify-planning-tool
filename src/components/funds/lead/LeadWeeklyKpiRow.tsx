"use client";

import {
  ArrowUpRight,
  CheckCircle2,
  Clock,
  FileWarning,
  Send,
  Wallet,
} from "lucide-react";
import {
  pendingLeadQueue,
  pendingAccountabilityQueue,
  weeklyFundRequests,
} from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";

// 6 KPI tiles for the Lead — counts + UGX values for each pipeline stage.
export function LeadWeeklyKpiRow() {
  const leadId = "STF-DM-014";
  const submittedCount = pendingLeadQueue(leadId).length;
  const submittedTotal = pendingLeadQueue(leadId).reduce(
    (a, r) => a + r.requestedAmount.amount,
    0,
  );
  const approvedCount = weeklyFundRequests.filter(
    (r) => r.programLeadId === leadId && r.status === "APPROVED",
  ).length;
  const disbursedCount = weeklyFundRequests.filter(
    (r) =>
      r.programLeadId === leadId &&
      ["DISBURSED", "RECEIVED", "IN_USE"].includes(r.status),
  ).length;
  const accountability = pendingAccountabilityQueue(leadId).length;
  const returned = weeklyFundRequests.filter(
    (r) =>
      r.programLeadId === leadId &&
      ["RETURNED_TO_STAFF", "ACCOUNTABILITY_RETURNED"].includes(r.status),
  ).length;
  const closed = weeklyFundRequests.filter(
    (r) => r.programLeadId === leadId && r.status === "CLOSED",
  ).length;

  const tiles = [
    {
      label: "Pending Approval",
      value: submittedCount.toString(),
      caption: formatMoney({ amount: submittedTotal, currency: "UGX" }),
      Icon: Clock,
      tone: "amber" as const,
    },
    {
      label: "Approved · Awaiting Funds",
      value: approvedCount.toString(),
      caption: "with Accountant",
      Icon: CheckCircle2,
      tone: "blue" as const,
    },
    {
      label: "Disbursed This Week",
      value: disbursedCount.toString(),
      caption: "in field",
      Icon: Send,
      tone: "emerald" as const,
    },
    {
      label: "Accountability Pending",
      value: accountability.toString(),
      caption: "receipts to review",
      Icon: FileWarning,
      tone: "violet" as const,
    },
    {
      label: "Returned",
      value: returned.toString(),
      caption: "awaiting staff fix",
      Icon: ArrowUpRight,
      tone: "rose" as const,
    },
    {
      label: "Closed This Month",
      value: closed.toString(),
      caption: "weeks fully accounted",
      Icon: Wallet,
      tone: "slate" as const,
    },
  ];

  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {tiles.map((t, i) => (
          <Tile key={t.label} {...t} stagger={`stagger-${i + 1}`} />
        ))}
      </div>
    </section>
  );
}

const TONE: Record<string, { bg: string; fg: string; glow: string }> = {
  emerald: { bg: "bg-emerald-100", fg: "text-emerald-700", glow: "glow-emerald" },
  amber:   { bg: "bg-amber-100",   fg: "text-amber-700",   glow: "glow-amber" },
  blue:    { bg: "bg-sky-100",     fg: "text-sky-700",     glow: "" },
  violet:  { bg: "bg-violet-100",  fg: "text-violet-700",  glow: "" },
  rose:    { bg: "bg-rose-100",    fg: "text-rose-700",    glow: "glow-rose" },
  slate:   { bg: "bg-slate-100",   fg: "text-slate-700",   glow: "" },
};

function Tile({
  label, value, caption, Icon, tone, stagger,
}: {
  label: string;
  value: string;
  caption: string;
  Icon: typeof Clock;
  tone: keyof typeof TONE;
  stagger: string;
}) {
  const t = TONE[tone];
  return (
    <div className={cn("card card-lift cursor-default tile-in p-3 flex flex-col gap-1.5", stagger)}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2 min-h-[24px] flex-1">
          {label}
        </div>
        <span className={cn("w-7 h-7 rounded-lg grid place-items-center shrink-0", t.bg)}>
          <Icon size={13} className={t.fg} />
        </span>
      </div>
      <div className={cn("text-[20px] font-extrabold tabular leading-none text-slate-900 num-hero", t.glow)}>
        {value}
      </div>
      <div className="text-caption muted font-semibold truncate">
        {caption}
      </div>
    </div>
  );
}
