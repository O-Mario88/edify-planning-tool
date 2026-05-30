"use client";

import type { WeeklyFundRequestStatus } from "@/lib/funds/weekly-fund-types";
import { STATUS_TONE } from "./status-tone";
import { cn } from "@/lib/utils";

export function StatusChip({
  status,
  size = "sm",
  withDot = true,
}: {
  status: WeeklyFundRequestStatus;
  size?: "xs" | "sm";
  withDot?: boolean;
}) {
  const tone = STATUS_TONE[status];
  const sizeCls =
    size === "xs"
      ? "text-[9.5px] px-1.5 py-[1px]"
      : "text-caption px-2 py-[2px]";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md font-extrabold whitespace-nowrap border",
        tone.chip,
        sizeCls,
      )}
    >
      {withDot && <span className={cn("w-1.5 h-1.5 rounded-full", tone.dot)} />}
      {tone.label}
    </span>
  );
}
