"use client";

import { ArrowUpRight, Banknote, Coins, Receipt, Send, ShieldAlert, Wallet } from "lucide-react";
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
import { cn } from "@/lib/utils";

// 6 KPI tiles across the top of the Accountant disbursement console.
// Each tile shows a finance-grade number (UGX), a sub-context line,
// and an arrow chip that links to the relevant queue.
export function AccountantKpiRow() {
  const pending = pendingDisbursementQueue();
  const pendingTotal = pending.reduce((a, r) => a + r.requestedAmount.amount, 0);
  const accountabilityCount = pendingAccountabilityQueue("STF-DM-014").length;

  const tiles = [
    {
      label: "Funds Available",
      value: formatMoney(totalAvailableBalance),
      caption: "Across 2 treasury batches",
      Icon: Coins,
      tone: "emerald" as const,
      delta: "+UGX 90M top-up",
    },
    {
      label: "Pending Disbursement",
      value: formatMoney({ amount: pendingTotal, currency: "UGX" }),
      caption: `${pending.length} approved this week`,
      Icon: Send,
      tone: "amber" as const,
    },
    {
      label: "Disbursed This Month",
      value: formatMoney(totalDisbursedThisMonth),
      caption: "May 2026 cycle",
      Icon: Banknote,
      tone: "blue" as const,
      delta: "+UGX 124M wk-3",
    },
    {
      label: "Accounted For",
      value: formatMoney(totalAccountedThisMonth),
      caption: "Receipts approved by Lead",
      Icon: Receipt,
      tone: "violet" as const,
    },
    {
      label: "Outstanding in Field",
      value: formatMoney(totalOutstanding),
      caption: `${accountabilityCount} accountabilities pending`,
      Icon: Wallet,
      tone: "rose" as const,
    },
    {
      label: "Treasury Received",
      value: formatMoney(totalReceivedThisMonth),
      caption: "RVP + HQ wires confirmed",
      Icon: ShieldAlert,
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
  label, value, caption, Icon, tone, delta, stagger,
}: {
  label: string;
  value: string;
  caption: string;
  Icon: typeof Coins;
  tone: keyof typeof TONE;
  delta?: string;
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
      <div className={cn("text-[17px] font-extrabold tabular leading-none text-slate-900 num-hero truncate", t.glow)}>
        {value}
      </div>
      <div className="flex items-center gap-1.5 text-caption min-w-0">
        {delta && (
          <span className="inline-flex items-center gap-0.5 font-bold shrink-0 text-emerald-700">
            <ArrowUpRight size={10} />
            {delta}
          </span>
        )}
        <span className="muted font-semibold truncate">{caption}</span>
      </div>
    </div>
  );
}
