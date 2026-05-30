"use client";

import { cn } from "@/lib/utils";

// Skeleton used as the `loading` fallback for every lazy-loaded chart.
// Heights default to 260 to match the most common chart-card body height
// and avoid CLS when the real chart hydrates.
export function ChartSkeleton({
  height = 260,
  variant = "bar",
  className,
}: {
  height?: number;
  variant?: "bar" | "line" | "donut" | "spark";
  className?: string;
}) {
  if (variant === "spark") {
    return (
      <div
        className={cn("rounded-md bg-[var(--color-edify-soft)]/70 overflow-hidden relative", className)}
        style={{ height }}
        aria-hidden
      >
        <div className="absolute inset-0 chart-skel-shimmer" />
      </div>
    );
  }

  if (variant === "donut") {
    return (
      <div
        className={cn("relative grid place-items-center", className)}
        style={{ height }}
        aria-hidden
      >
        <div className="rounded-full border-[10px] border-[var(--color-edify-soft)]/80 chart-skel-shimmer-mask" style={{ width: Math.min(height - 32, 160), height: Math.min(height - 32, 160) }} />
      </div>
    );
  }

  // Bar / line — vertical pill skeleton row.
  return (
    <div
      className={cn("relative overflow-hidden", className)}
      style={{ height }}
      aria-busy="true"
      aria-label="Loading chart"
    >
      <div className="absolute inset-0 grid grid-cols-12 gap-2 items-end px-1 pb-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="rounded-t-md bg-[var(--color-edify-soft)]/80 chart-skel-bar"
            style={{ height: `${30 + ((i * 17) % 60)}%` }}
          />
        ))}
      </div>
      <div className="absolute inset-0 chart-skel-shimmer pointer-events-none" />
    </div>
  );
}
