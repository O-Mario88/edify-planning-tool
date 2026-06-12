// CD Risk Summary surface (spec layer #8). Server component — the Day-5+
// escalations that have reached the Country Director. Drops onto the CD/Director
// dashboard.

import Link from "next/link";
import { AlertOctagon } from "lucide-react";
import { cdRiskSummary } from "@/lib/escalation/escalation-engine";

export function CdRiskSummaryCard() {
  const items = cdRiskSummary();

  return (
    <section className="rounded-2xl border border-rose-200 bg-rose-50/40 p-4 dark:border-rose-500/30 dark:bg-rose-500/5">
      <header className="mb-2 flex items-center gap-2">
        <AlertOctagon size={15} className="text-rose-600" />
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Risk summary — escalated to you</h2>
        <span className="ml-auto text-xs font-semibold text-rose-600">{items.length}</span>
      </header>
      {items.length === 0 ? (
        <p className="text-sm text-emerald-600">No items have escalated to Day-5 risk. The chain is flowing.</p>
      ) : (
        <ul className="divide-y divide-rose-100 dark:divide-rose-500/20">
          {items.slice(0, 10).map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-3 py-2 text-xs">
              <span className="min-w-0">
                <span className="font-medium text-slate-700 dark:text-slate-200">{i.category}</span>
                <span className="text-slate-400"> — {i.label} ({i.ageDays}d)</span>
              </span>
              {i.href && (
                <Link href={i.href} className="shrink-0 font-medium text-rose-600 no-underline hover:underline">Open →</Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
