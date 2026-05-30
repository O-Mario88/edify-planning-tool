"use client";

// PartnerImpactByArea — per-intervention-area breakdown of partner
// impact. Each row: area name, supported count, measured count, avg
// score change (with bar), improved/declined split.

import { TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { partnerImpactRecords, summariseByArea } from "@/lib/partner/partner-impact";

export function PartnerImpactByArea() {
  const rows = summariseByArea(partnerImpactRecords);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.avgChange)));
  return (
    <section className="card p-3.5">
      <header className="mb-3">
        <h3 className="text-body-lg font-extrabold tracking-tight">Impact by intervention area</h3>
        <p className="text-[11.5px] muted mt-0.5">
          Average SSA delta in each area where this partner delivered support.
        </p>
      </header>
      <ul className="space-y-2.5">
        {rows.map((r) => {
          const positive = r.avgChange >= 0;
          const pct = Math.abs(r.avgChange) / max;
          return (
            <li key={r.area} className="grid grid-cols-12 gap-3 items-center">
              <div className="col-span-12 sm:col-span-4 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{r.area}</div>
                <div className="text-caption muted leading-tight">
                  {r.supported} supported · {r.measured} measured
                </div>
              </div>
              <div className="col-span-7 sm:col-span-5">
                <div className="h-2 w-full rounded-full bg-[var(--color-edify-soft)] relative overflow-hidden">
                  <div
                    className={cn(
                      "absolute top-0 bottom-0 transition-all",
                      positive ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-500",
                    )}
                    style={{ width: `${(pct * 50).toFixed(0)}%` }}
                  />
                  <div className="absolute top-0 bottom-0 left-1/2 w-px bg-[var(--color-edify-divider)]" aria-hidden />
                </div>
              </div>
              <div className="col-span-5 sm:col-span-3 flex items-center justify-end gap-2">
                <span className={cn(
                  "inline-flex items-center gap-1 text-body font-extrabold tabular",
                  positive ? "text-emerald-700" : r.avgChange < 0 ? "text-rose-700" : "muted",
                )}>
                  {positive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                  {r.avgChange > 0 ? `+${r.avgChange}` : r.avgChange.toFixed(1)}
                </span>
                <span className="text-caption muted whitespace-nowrap">
                  {r.improved}↑ / {r.declined}↓
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
