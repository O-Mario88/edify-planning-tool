"use client";

import { CheckCircle2 } from "lucide-react";
import { teamFooterMetrics } from "@/lib/team-targets-billion-mock";

// Footer mini-metrics strip — 7 team-level stats anchored at the
// bottom of the page so high-frequency lookups (verified activities,
// open support reviews, last sync) are always one glance away.
export function TeamFooterStrip() {
  return (
    <section className="card rounded-2xl p-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3 lg:gap-4">
      {teamFooterMetrics.map((m, i) => (
        <div
          key={m.key}
          className={`min-w-0 ${i === teamFooterMetrics.length - 1 ? "" : "lg:border-r lg:border-[#eef2f4] lg:pr-3"}`}
        >
          <div className="text-[9.5px] uppercase tracking-wide muted font-bold leading-tight">
            {m.label}
          </div>
          <div className={`text-[16px] font-extrabold tabular leading-none mt-1 ${m.key === "last_sync" ? "text-emerald-700 inline-flex items-center gap-1" : "text-slate-900"}`}>
            {m.key === "last_sync" && <CheckCircle2 size={13} />}
            {m.value}
          </div>
          <div className="text-[10px] muted font-semibold mt-0.5 truncate">
            {m.caption}
          </div>
        </div>
      ))}
    </section>
  );
}
