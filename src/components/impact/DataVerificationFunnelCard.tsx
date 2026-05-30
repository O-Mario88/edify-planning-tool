import Link from "next/link";
import { TrendingUp, ArrowUpRight } from "lucide-react";
import {
  verificationFunnel,
  verificationRate,
  type FunnelStage,
} from "@/lib/impact-mock";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/utils";

// Data Verification Funnel — the analytics card.
//
// Replaced the old "5 flat color bars" Tableau-2018 look with a more
// honest reading of the underlying data plus the segmented-bar
// aesthetic from Stripe / Linear analytics:
//
//   • The first 3 stages (In Review, Verified, Failed QC) are TERMINAL
//     states of the 12,842 uploads — they sum to exactly that total.
//     So they're shown as a single SEGMENTED rail at the top, not five
//     separate bars. The rail is one continuous surface; the eye reads
//     proportion at a glance.
//   • Resolved is a recovery metric (records that bounced back from
//     Failed QC). It's not on the same axis as the terminal states; it
//     belongs in a footer line, not the main bar.
//   • The headline is the verification rate (76.5%) with a period
//     delta — that's the number leadership actually cares about. Stage
//     rows underneath are the breakdown.
//
// The change kills the "Tableau 2018" feeling without losing any data.

const SEGMENT_FILL: Record<FunnelStage["tone"], string> = {
  blue:  "bg-blue-500",
  sky:   "bg-sky-500",
  amber: "bg-amber-500",
  rose:  "bg-rose-500",
  green: "bg-emerald-500",
};
const SEGMENT_DOT: Record<FunnelStage["tone"], string> = {
  blue:  "bg-blue-500",
  sky:   "bg-sky-500",
  amber: "bg-amber-500",
  rose:  "bg-rose-500",
  green: "bg-emerald-500",
};

// Stage 0 (Uploaded) is the denominator — it shows as the headline.
// Stages 1..3 (In Review / Verified / Failed QC) are the terminal
// partition. Stage 4 (Resolved) is the recovery metric, rendered as
// the footer line.
function partitionStages(): FunnelStage[] {
  return verificationFunnel.filter((s) =>
    s.key === "in-review" || s.key === "verified" || s.key === "failed-qc"
  );
}

function uploadedTotal(): number {
  return verificationFunnel.find((s) => s.key === "uploaded")?.value ?? 0;
}

function resolvedStage(): FunnelStage | undefined {
  return verificationFunnel.find((s) => s.key === "resolved");
}

export function DataVerificationFunnelCard() {
  const stages = partitionStages();
  const total = uploadedTotal();
  const resolved = resolvedStage();

  return (
    <article className="card p-3.5 flex flex-col h-full">
      <SectionHeader
        tier="operational"
        title="Verification Funnel"
        meta={
          <Link
            href="/data-verification"
            className="t-caption font-bold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-0.5"
          >
            Open Queue <ArrowUpRight size={11} />
          </Link>
        }
      />

      {/* Headline — the number leadership reads first */}
      <div className="mt-4 flex items-baseline gap-3">
        <span className="num-hero text-[36px] font-extrabold leading-none tabular text-[var(--text-primary)]">
          {verificationRate}%
        </span>
        <span className="inline-flex items-center gap-0.5 t-caption font-bold text-emerald-700 dark:text-emerald-400">
          <TrendingUp size={11} /> +2.1% vs Apr
        </span>
      </div>
      <p className="t-caption text-muted mt-1">
        of {total.toLocaleString()} uploaded records this period
      </p>

      {/* Segmented partition rail — one continuous bar, three states */}
      <div className="mt-5">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--color-edify-divider)]">
          {stages.map((s) => (
            <div
              key={s.key}
              className={cn("h-full transition-[width] duration-500", SEGMENT_FILL[s.tone])}
              style={{ width: s.share }}
              title={`${s.label}: ${s.value.toLocaleString()} (${s.share})`}
            />
          ))}
        </div>

        {/* Stage detail rows */}
        <ul className="mt-4 space-y-2.5">
          {stages.map((s) => (
            <li key={s.key}>
              <Link
                href={s.href}
                className="group flex items-center gap-3 -mx-2 px-2 py-1 rounded-lg hover:bg-[var(--surface-hover)] transition-colors"
              >
                <span className={cn("w-2 h-2 rounded-full shrink-0", SEGMENT_DOT[s.tone])} />
                <span className="t-body-lg font-bold text-[var(--text-primary)] flex-1 min-w-0">
                  {s.label}
                </span>
                <span className="num-hero text-[15px] font-extrabold tabular text-[var(--text-primary)]">
                  {s.value.toLocaleString()}
                </span>
                <span className="t-caption text-muted tabular w-12 text-right">
                  {s.share}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>

      {/* Recovery footer — resolved is a separate metric, treated as
          an annotation rather than a peer stage. */}
      {resolved ? (
        <div className="mt-auto pt-4 border-t border-[var(--color-edify-divider)] flex items-center justify-between">
          <div>
            <p className="section-h-micro">Recovery</p>
            <p className="t-caption text-muted mt-0.5">
              Records resolved after a QC failure
            </p>
          </div>
          <Link
            href={resolved.href}
            className="text-right group hover:underline"
          >
            <p className="num-hero text-[18px] font-extrabold tabular text-emerald-700 dark:text-emerald-400 leading-none">
              {resolved.value.toLocaleString()}
            </p>
            <p className="t-caption text-muted mt-0.5 tabular">
              {resolved.share} of base
            </p>
          </Link>
        </div>
      ) : null}
    </article>
  );
}
