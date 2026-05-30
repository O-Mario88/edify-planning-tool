import Link from "next/link";
import {
  partnerScores,
  partnerOverallAverage,
  type PartnerScore,
} from "@/lib/impact-mock";
import { cn } from "@/lib/utils";

const BAR: Record<PartnerScore["tone"], string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  rose:  "bg-rose-500",
};

export function PartnerPerformanceCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-baseline justify-between mb-3">
        <div className="min-w-0">
          <h2 className="text-body-lg font-extrabold tracking-tight">Partner Performance</h2>
          <p className="text-caption muted">Verification Rate</p>
        </div>
        <Link
          href="/partners"
          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline shrink-0"
        >
          View All
        </Link>
      </header>

      <ul className="space-y-3 flex-1">
        {partnerScores.map((p) => (
          <li key={p.key}>
            <Link href={p.href} className="block group">
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="text-[12px] font-semibold truncate group-hover:text-[var(--color-edify-primary)]">
                  {p.name}
                </span>
                <span className="text-[12px] font-extrabold tabular shrink-0">{p.pct}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div
                  className={cn("h-full rounded-full", BAR[p.tone])}
                  style={{ width: `${p.pct}%` }}
                />
              </div>
            </Link>
          </li>
        ))}
      </ul>

      <div className="mt-3 pt-3 border-t border-[var(--color-edify-border)] flex items-center justify-between">
        <span className="text-[12px] font-extrabold tracking-tight">Overall Average</span>
        <span className="text-body-lg font-extrabold tabular text-emerald-600">
          {partnerOverallAverage}%
        </span>
      </div>
    </article>
  );
}
