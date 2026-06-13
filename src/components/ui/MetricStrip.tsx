"use client";

// MetricStrip — the dense alternative to a grid of KPI tiles.
//
// WHY: big KPI tiles work at ≤4 in a row; past that they become a noisy,
// equal-weight grid where nothing leads. A strip lays many metrics as one
// continuous band of flush, hairline-separated cells — value + small label,
// no sparklines, optional tiny icon — so 8–13 metrics read as a single
// scannable stat line instead of a wall of boxes. Reserve the big-tile
// treatment for the ≤4 hero metrics a user actually acts on.
//
// Tone: "alert" tints the value (needs-attention metrics — unclustered, pending);
// "good" tints it positive. Cells can deep-link via `href`.

import Link from "next/link";
import { ArrowUpRight, ArrowDownRight, Minus, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type MetricDelta = { dir: "up" | "down" | "flat"; text: string };

export type MetricCell = {
  key: string;
  label: string;
  value: string | number;
  /** Small muted unit beside the value ("%", "schools"). */
  unit?: string;
  /** Faint sub-line — e.g. a proportion "76.9%" or "of 13". */
  caption?: string;
  /** Trend sub-line (colored + arrow). Takes precedence over caption. */
  delta?: MetricDelta;
  tone?: "default" | "alert" | "good";
  icon?: LucideIcon;
  /** Makes the cell a link (e.g. deep-link into a filtered list). */
  href?: string;
  /** Makes the cell a button (e.g. a filter trigger). Ignored if href is set. */
  onClick?: () => void;
  /** Highlights the cell as the active selection (for onClick filter cells). */
  active?: boolean;
};

const DELTA_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus };
const DELTA_FG = {
  up: "text-emerald-600",
  down: "text-rose-600",
  flat: "muted",
};

const VALUE_TONE: Record<NonNullable<MetricCell["tone"]>, string> = {
  default: "text-[var(--text-primary)]",
  alert: "text-rose-600",
  good: "text-emerald-600",
};

// Cells use collapsing 1px borders (a spreadsheet-like band) so any count wraps
// cleanly without leading/trailing dividers — the strip reads as one unit.
const COLS =
  "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6";

export function MetricStrip({
  metrics,
  title,
  className,
  columns,
  bare = false,
}: {
  metrics: MetricCell[];
  title?: string;
  className?: string;
  /** Override the responsive column classes when a specific count fits better. */
  columns?: string;
  /** Render just the hairline cell grid (no card/header) so it can drop into an
   *  existing card in place of a tile grid without nesting cards. */
  bare?: boolean;
}) {
  const grid = (
    <div className={cn("grid border-t border-l border-[var(--color-edify-divider)]", columns ?? COLS)}>
      {metrics.map((m) => (
        <Cell key={m.key} cell={m} />
      ))}
    </div>
  );
  if (bare) {
    return <div className={cn("rounded-xl overflow-hidden", className)}>{grid}</div>;
  }
  return (
    <section className={cn("card rounded-2xl overflow-hidden", className)}>
      {title && (
        <header className="px-3.5 pt-3 pb-2 border-b border-[var(--color-edify-divider)]">
          <h2 className="text-[12px] font-extrabold tracking-tight uppercase muted">{title}</h2>
        </header>
      )}
      {grid}
    </section>
  );
}

function Cell({ cell }: { cell: MetricCell }) {
  const Icon = cell.icon;
  const tone = cell.tone ?? "default";
  const DeltaIcon = cell.delta ? DELTA_ICON[cell.delta.dir] : null;
  const body = (
    <>
      <div className="flex items-center gap-1 text-[10px] muted font-bold uppercase tracking-wide leading-tight">
        {Icon && <Icon size={10} className="shrink-0" />}
        <span className="truncate">{cell.label}</span>
      </div>
      <div className="flex items-baseline gap-1 mt-1.5 min-w-0">
        <span className={cn("text-[17px] font-extrabold tabular leading-none truncate", VALUE_TONE[tone])}>
          {typeof cell.value === "number" ? cell.value.toLocaleString() : cell.value}
        </span>
        {cell.unit && <span className="text-[11px] muted font-semibold leading-none">{cell.unit}</span>}
      </div>
      {cell.delta ? (
        <div className={cn("flex items-center gap-0.5 text-[10px] font-bold tabular mt-0.5 truncate", DELTA_FG[cell.delta.dir])}>
          {DeltaIcon && <DeltaIcon size={10} className="shrink-0" />}
          <span className="truncate">{cell.delta.text}</span>
        </div>
      ) : cell.caption ? (
        <div className="text-[10px] muted font-medium mt-0.5 truncate">{cell.caption}</div>
      ) : null}
    </>
  );

  const base = "block px-3 py-2.5 border-r border-b border-[var(--color-edify-divider)] min-w-0";
  const activeCls = cell.active ? "bg-[var(--color-edify-soft)]/70 ring-1 ring-inset ring-[var(--color-edify-primary)]/40" : "";
  if (cell.href) {
    return (
      <Link href={cell.href} className={cn(base, "transition-colors hover:bg-[var(--color-edify-soft)]/50", activeCls)}>
        {body}
      </Link>
    );
  }
  if (cell.onClick) {
    return (
      <button type="button" onClick={cell.onClick} className={cn(base, "text-left w-full transition-colors hover:bg-[var(--color-edify-soft)]/50", activeCls)}>
        {body}
      </button>
    );
  }
  return <div className={cn(base, activeCls)}>{body}</div>;
}
