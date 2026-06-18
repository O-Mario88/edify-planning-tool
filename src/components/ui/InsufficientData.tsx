import { type ReactNode } from "react";
import { Database } from "lucide-react";
import { cn } from "@/lib/utils";

// Production-safety empty state — COMPACT by design.
//
// Rendered in place of any surface not yet wired to live backend source
// records, so production NEVER shows fabricated numbers. It is a tight,
// horizontal insight card (icon + two lines + optional action) — NOT a giant
// centered hero — so an empty surface never dominates the layout or strands a
// dead column. Pair with `isMockAllowed()` from "@/lib/mock-policy".
//
//   if (!isMockAllowed()) return <InsufficientData surface="the SSA heatmap" />;
//   <InsufficientData surface="the fund queue" action={<a className="btn btn-sm" href="/analytics">Open analytics</a>} />
//
// Honest by design: it shows nothing rather than a placeholder figure a leader
// could mistake for real data — but it stays small and offers a next step.
export function InsufficientData({
  surface = "this view",
  detail,
  action,
  className,
}: {
  surface?: string;
  detail?: string;
  /** Optional next-step control (e.g. "Open analytics", "View data quality"). */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "card p-3.5 flex items-start gap-3 rounded-2xl",
        className,
      )}
    >
      <span className="h-9 w-9 shrink-0 rounded-xl grid place-items-center bg-[var(--color-warn-soft)] text-[var(--color-edify-orange)]">
        <Database size={16} />
      </span>
      <div className="flex-1 min-w-0">
        <h3 className="text-[12.5px] font-semibold tracking-tight leading-tight">
          Insufficient data
        </h3>
        <p className="text-[11.5px] text-secondary leading-snug mt-0.5">
          {detail ??
            `${surface[0].toUpperCase()}${surface.slice(1)} is not yet connected to live data — figures are withheld until they trace to source records.`}
        </p>
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}
