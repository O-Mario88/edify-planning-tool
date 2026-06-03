import Link from "next/link";
import { Network, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function ClusterReadinessCard({
  clustered,
  unclustered,
  needsReview,
  hrefAll = "/clusters/assign",
  title = "Cluster setup",
}: {
  clustered: number;
  unclustered: number;
  needsReview?: number;
  hrefAll?: string;
  title?: string;
}) {
  const review = needsReview ?? 0;
  const total = clustered + unclustered + review;
  const pct = total > 0 ? Math.round((clustered / total) * 100) : 0;

  return (
    <div className="card rounded-2xl p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          {title}
        </h3>
        <Network className="h-4 w-4 text-[var(--color-edify-primary)]" />
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2">
          <div className="text-[18px] font-extrabold tabular tracking-tight text-emerald-500">
            {clustered}
          </div>
          <div className="muted text-[11px]">Clustered</div>
        </div>
        <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2">
          <div className="text-[18px] font-extrabold tabular tracking-tight text-rose-500">
            {unclustered}
          </div>
          <div className="muted text-[11px]">Unclustered</div>
        </div>
        {review > 0 ? (
          <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2">
            <div className="text-[18px] font-extrabold tabular tracking-tight text-amber-500">
              {review}
            </div>
            <div className="muted text-[11px]">Needs review</div>
          </div>
        ) : null}
      </div>

      <div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-edify-soft)]">
          <div
            className="h-full rounded-full bg-emerald-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="muted mt-1 text-[11px] tabular">{pct}% clustered</div>
      </div>

      {unclustered > 0 ? (
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
