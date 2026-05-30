"use client";

import { ArrowUpRight, CheckCircle2, Plus } from "lucide-react";
import { fundsReceived } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { cn } from "@/lib/utils";

// Funds Received Confirmation panel.
//
// This is the legal "did the money land?" register that gates every
// downstream disbursement. The Accountant confirms each treasury wire
// here; only confirmed batches contribute to the available balance.
export function FundsReceivedPanel() {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight">Funds Received at Country</h3>
          <p className="text-caption muted font-semibold leading-tight">
            Treasury receipts gating this month&apos;s disbursements
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-[11.5px] font-extrabold"
        >
          <Plus size={11} />
          Log receipt
        </button>
      </header>

      <ul className="flex flex-col gap-2">
        {fundsReceived.map((r, i) => {
          const allocatedPct = (r.totalAllocated.amount / r.totalReceived.amount) * 100;
          const stagger = ["stagger-1", "stagger-2"][i] ?? "";
          return (
            <li
              key={r.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white p-3 tile-in card-lift",
                stagger,
              )}
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[12px] font-extrabold text-slate-900 truncate">
                      {r.fromSource === "RVP_OFFICE" ? "RVP Office" : r.fromSource === "HQ_TREASURY" ? "HQ Treasury" : "Partner"}
                    </span>
                    <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-emerald-100 text-emerald-700 border border-emerald-200">
                      <CheckCircle2 size={9} />
                      Confirmed
                    </span>
                  </div>
                  <div className="text-caption muted font-semibold mt-0.5 truncate">
                    {r.receivedOnIso} · {r.reference}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-body-lg font-extrabold tabular num-hero text-slate-900 leading-none">
                    {formatMoney(r.totalReceived)}
                  </div>
                  <div className="text-[10px] muted font-semibold mt-0.5">received</div>
                </div>
              </div>

              {/* Allocation bar */}
              <div className="mt-2">
                <div className="flex items-center justify-between text-[10px] mb-1">
                  <span className="muted font-semibold">
                    Allocated <span className="text-slate-700 font-extrabold tabular">{formatMoney(r.totalAllocated)}</span>
                  </span>
                  <span className="muted font-semibold">
                    Available <span className="text-emerald-700 font-extrabold tabular">{formatMoney(r.availableBalance)}</span>
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-emerald-600"
                    style={{ width: `${Math.min(100, allocatedPct).toFixed(1)}%` }}
                  />
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <a
        href="#funds-receipts-all"
        className="inline-flex items-center gap-1 text-[11px] font-extrabold text-[var(--color-edify-primary)] mt-2.5 self-end"
      >
        Open ledger
        <ArrowUpRight size={10} />
      </a>
    </article>
  );
}
