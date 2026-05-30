import Link from "next/link";
import { ArrowUpRight, AlertOctagon } from "lucide-react";
import {
  qualityCheckSeverity,
  qualityCheckTotal,
} from "@/lib/impact-mock";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/utils";

// Quality Check Status — replaces the donut + legend with severity-
// ranked rows that each carry their own proportional bar.
//
// Why the change: donut + legend is the single most generic dashboard
// pattern of the last decade. It forces the eye to ping-pong between
// the wedge and its label to read any one number. The Linear / Sentry
// / Honeycomb aesthetic for issue severity is direct: stack severities
// top-to-bottom (worst first), give each row its own sparkbar showing
// share of total, and let the count + share read inline. Faster scan,
// more authoritative look, no chartjs dependency for this card.

export function QualityCheckStatusCard() {
  // Max-share denominator so bars use the FULL row width when a single
  // severity dominates (here: Major 39%). Anchoring to max instead of
  // 100% reads better because the visual weight tracks the data shape.
  const maxShare = Math.max(
    ...qualityCheckSeverity.map((s) => parseFloat(s.share))
  );

  return (
    <article className="card p-3.5 h-full flex flex-col">
      <SectionHeader
        tier="operational"
        title="Quality Issues"
        icon={
          <span className="w-8 h-8 rounded-lg bg-rose-50 dark:bg-rose-500/10 text-rose-600 dark:text-rose-400 grid place-items-center">
            <AlertOctagon size={14} />
          </span>
        }
        meta={
          <div className="text-right">
            <p className="num-hero text-[18px] font-extrabold tabular leading-none text-[var(--text-primary)]">
              {qualityCheckTotal.toLocaleString()}
            </p>
            <p className="t-tiny text-muted mt-0.5">open</p>
          </div>
        }
      />

      <ul className="mt-5 space-y-3.5 flex-1">
        {qualityCheckSeverity.map((s) => {
          const sharePct = parseFloat(s.share);
          const barWidth = `${(sharePct / maxShare) * 100}%`;
          const isCritical = s.key === "critical";
          return (
            <li key={s.key}>
              <Link
                href={s.href}
                className="group block -mx-2 px-2 py-1 rounded-lg hover:bg-[var(--surface-hover)] transition-colors"
              >
                <div className="flex items-center gap-2.5 mb-1.5">
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className={cn(
                    "flex-1 min-w-0 t-body-lg",
                    isCritical ? "font-extrabold text-[var(--text-primary)]" : "font-bold text-[var(--text-primary)]",
                  )}>
                    {s.label}
                  </span>
                  <span className="num-hero font-extrabold tabular text-[var(--text-primary)]">
                    {s.value.toLocaleString()}
                  </span>
                  <span className="t-caption text-muted tabular w-12 text-right">
                    {s.share}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
                  <div
                    className="h-full rounded-full transition-[width] duration-500"
                    style={{ width: barWidth, backgroundColor: s.color }}
                  />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>

      <Link
        href="/quality-checks"
        className="mt-5 inline-flex items-center justify-center gap-1 h-9 rounded-xl border border-[var(--color-edify-border)] t-body font-bold text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-colors"
      >
        Review All Issues <ArrowUpRight size={12} />
      </Link>
    </article>
  );
}
