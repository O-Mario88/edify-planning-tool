"use client";

import { Inbox, RotateCcw } from "lucide-react";

export type TileFilterEmptyStateProps = {
  title?: string;
  subtext?: string;
  onReset: () => void;
};

export function TileFilterEmptyState({
  title = "No records match this filter.",
  subtext = "Try changing FY, quarter, district, or reset the view.",
  onReset,
}: TileFilterEmptyStateProps) {
  return (
    <div className="card p-8 flex flex-col items-center justify-center text-center gap-3">
      <div className="w-12 h-12 rounded-full grid place-items-center tile-filter-empty-icon">
        <Inbox size={20} />
      </div>
      <div>
        <div className="text-[14px] font-extrabold tracking-tight">{title}</div>
        <p className="mt-1 text-[12px] muted max-w-sm">{subtext}</p>
      </div>
      <button
        type="button"
        onClick={onReset}
        className="tile-filter-btn-primary inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-bold"
      >
        <RotateCcw size={12} />
        Reset View
      </button>
    </div>
  );
}
