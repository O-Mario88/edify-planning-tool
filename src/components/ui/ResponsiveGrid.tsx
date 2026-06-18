import { type CSSProperties, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ResponsiveGrid — content-aware section grid.
//
// The fix for lopsided dashboards: instead of a fixed `grid-cols-2` that
// strands an empty column when a card is missing/compact, this uses
// `auto-fit` + `minmax` so the column COUNT follows the available width, and
// `grid-auto-flow: dense` so short cards backfill gaps left by taller ones.
// The result: cards size to their content and the row repacks — no dead zone,
// no card floating alone beside a blank column.
//
//   <ResponsiveGrid min={300}>     // cards are ≥300px, as many per row as fit
//     <DataCard .../>              // a card can claim more width with
//     <InsightCard style={{ gridColumn: "span 2" }} .../>  // an explicit span
//   </ResponsiveGrid>
//
// `min` uses `min(Npx, 100%)` so a single card never overflows a narrow
// viewport (the classic auto-fit mobile-overflow bug).
export function ResponsiveGrid({
  children,
  /** Minimum card width in px before the grid drops to fewer columns. */
  min = 280,
  /** Gap between cards, in px. */
  gap = 16,
  /** Backfill gaps with shorter cards (default on). */
  dense = true,
  className,
  style,
}: {
  children: ReactNode;
  min?: number;
  gap?: number;
  dense?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={cn("grid", className)}
      style={{
        gridTemplateColumns: `repeat(auto-fit, minmax(min(${min}px, 100%), 1fr))`,
        gap: `${gap}px`,
        gridAutoFlow: dense ? "row dense" : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
