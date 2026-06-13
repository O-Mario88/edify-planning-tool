import Link from "next/link";
import { Network, CheckCircle2 } from "lucide-react";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { cn } from "@/lib/utils";

export function ClusterReadinessCard({
  clustered,
  unclustered,
  needsReview,
  hrefAll = "/schools",
  title = "Cluster setup",
  actionable = true,
}: {
  clustered: number;
  unclustered: number;
  needsReview?: number;
  hrefAll?: string;
  title?: string;
  // When false (e.g. CD viewing aggregates), show the readiness stat without
  // the operational "Assign to clusters" CTA — cluster assignment is CCEO/PL/IA
  // work, and the CD has no directory access (spec §18).
  actionable?: boolean;
}) {
  const review = needsReview ?? 0;
  const total = clustered + unclustered + review;
  const pct = total > 0 ? Math.round((clustered / total) * 100) : 0;

  const cells: MetricCell[] = [
    { key: "clustered", label: "Clustered", value: clustered, tone: "good" },
    { key: "unclustered", label: "Unclustered", value: unclustered, tone: "alert" },
    ...(review > 0
      ? [{ key: "review", label: "Needs review", value: review } as MetricCell]
      : []),
  ];

  return (
    <div className="card rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          {title}
        </h3>
        <Network className="h-4 w-4 text-[var(--color-edify-primary)]" />
      </div>

      <MetricStrip
        bare
        columns={review > 0 ? "grid-cols-3" : "grid-cols-2"}
        metrics={cells}
      />

      <div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-edify-soft)]">
          <div
            className="h-full rounded-full bg-emerald-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="muted mt-1 text-[11px] tabular">{pct}% clustered</div>
      </div>

      {unclustered > 0 && !actionable ? (
        <div className="muted text-[12px] tabular">{unclustered} unclustered</div>
      ) : unclustered > 0 ? (
        <Link
          href={hrefAll}
          className={cn(
            "inline-flex items-center justify-center rounded-xl px-3 py-2",
            "text-[12.5px] font-extrabold tracking-tight",
            "bg-[var(--color-edify-primary)] text-white",
          )}
        >
          Assign {unclustered} to clusters →
        </Link>
      ) : (
        <div className="muted flex items-center gap-1.5 text-[12px]">
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          All schools clustered
        </div>
      )}
    </div>
  );
}
