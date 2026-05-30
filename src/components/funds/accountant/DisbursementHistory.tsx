"use client";

import { ArrowUpRight, Banknote, Building2, Smartphone, Wallet } from "lucide-react";
import { activeDisbursements } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";

const METHOD_ICON = {
  MobileMoney:  Smartphone,
  BankTransfer: Building2,
  Cash:         Wallet,
  Cheque:       Banknote,
} as const;

const METHOD_TONE = {
  MobileMoney:  "bg-emerald-100 text-emerald-700",
  BankTransfer: "bg-sky-100    text-sky-700",
  Cash:         "bg-amber-100  text-amber-700",
  Cheque:       "bg-violet-100 text-violet-700",
} as const;

// Disbursement History.
//
// Reverse-chronological log of every disbursement. Each row shows
// the method, reference, staff, amount, and whether staff has
// confirmed receipt (one of the audit-grade signals).
export function DisbursementHistory() {
  const records = activeDisbursements().slice(0, 8);

  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Disbursement History</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Latest cash movements · audit trail
          </p>
        </div>
        <a
          href="#dsb-history-all"
          className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)]"
        >
          View All
          <ArrowUpRight size={10} />
        </a>
      </header>

      <ul className="flex flex-col gap-1.5">
        {records.map((d, i) => {
          const Icon = METHOD_ICON[d.method];
          const tone = METHOD_TONE[d.method];
          const stagger = `stagger-${(i % 6) + 1}`;
          const confirmed = !!d.receiptConfirmedByStaffAt;
          const dateLabel = new Date(d.disbursedAt).toLocaleDateString("en-GB", {
            day: "2-digit", month: "short",
          });
          return (
            <li
              key={d.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white px-2.5 py-2 flex items-center gap-2.5 tile-in card-lift",
                stagger,
              )}
            >
              <span className={cn("w-7 h-7 rounded-lg grid place-items-center shrink-0", tone)}>
                <Icon size={12} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold text-slate-900 truncate">
                  {d.staffName}
                  <span className="text-slate-400 font-medium"> — </span>
                  <span className="text-slate-600 font-semibold">{d.method}</span>
                </div>
                <div className="text-[10px] muted font-semibold truncate">
                  {d.reference} · {dateLabel}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-body font-extrabold tabular num-hero text-slate-900 leading-none">
                  {formatMoney(d.amount)}
                </div>
                <div className="text-[9.5px] font-semibold mt-0.5">
                  {confirmed ? (
                    <span className="text-emerald-700">Receipt OK</span>
                  ) : (
                    <span className="text-amber-700">Receipt pending</span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
