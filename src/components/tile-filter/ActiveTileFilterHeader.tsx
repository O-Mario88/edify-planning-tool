"use client";

// ActiveTileFilterHeader — the prominent banner shown above a filtered
// result view. Title, count, description, and the reset/export/plan
// action triad. Reads as "you are in a focused view; here's how to
// leave".

import { Download, RotateCcw, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TileFilterAction, TileFilterSpec } from "./types";

export type ActiveTileFilterHeaderProps = {
  filter: TileFilterSpec;
  count: number;
  onReset: () => void;
  onExport?: () => void;
  primaryAction?: TileFilterAction;
  breadcrumb?: string;
};

export function ActiveTileFilterHeader({
  filter,
  count,
  onReset,
  onExport,
  primaryAction,
  breadcrumb,
}: ActiveTileFilterHeaderProps) {
  const action = primaryAction ?? filter.primaryAction;
  return (
    <section
      role="region"
      aria-label="Active tile filter"
      className={cn(
        "tile-filter-header",
        "rounded-2xl border px-4 py-4 lg:px-5 lg:py-5",
        "flex flex-col gap-3",
      )}
    >
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0 flex-1">
          {breadcrumb && (
            <div className="text-[10.5px] uppercase tracking-wide font-bold tile-filter-header-eyebrow mb-1.5">
              {breadcrumb}
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            <Sparkles size={14} className="tile-filter-header-spark shrink-0" />
            <h2 className="text-[16px] sm:text-[18px] font-extrabold tracking-tight tile-filter-header-title">
              Viewing: {filter.label}
            </h2>
            <span className="tile-filter-header-count inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-extrabold tabular">
              {count} {count === 1 ? "match" : "matches"}
            </span>
          </div>
          <p className="mt-1.5 text-[12.5px] leading-snug tile-filter-header-desc max-w-2xl">
            {filter.description}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap shrink-0">
          <button
            type="button"
            onClick={onReset}
            className="tile-filter-btn-reset inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-bold whitespace-nowrap"
          >
            <RotateCcw size={12} />
            Reset View
          </button>
          {onExport && (
            <button
              type="button"
              onClick={onExport}
              className="tile-filter-btn-secondary inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-semibold whitespace-nowrap"
            >
              <Download size={12} />
              Export
            </button>
          )}
          {action?.href && (
            <a
              href={action.href}
              className="tile-filter-btn-primary inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-bold whitespace-nowrap"
            >
              {action.label}
            </a>
          )}
          {action?.onClick && !action.href && (
            <button
              type="button"
              onClick={action.onClick}
              className="tile-filter-btn-primary inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-bold whitespace-nowrap"
            >
              {action.label}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

// Standalone close chip — usable inside any card to clear the filter
// without going through the header (e.g. drawer headers).
export function ResetTileFilterChip({ onReset }: { onReset: () => void }) {
  return (
    <button
      type="button"
      onClick={onReset}
      className="tile-filter-btn-secondary inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[11px] font-semibold"
    >
      <X size={11} />
      Clear filter
    </button>
  );
}
