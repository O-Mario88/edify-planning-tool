"use client";

import { cn } from "@/lib/utils";
import { categoryMeta, PRIORITY_ICON } from "@/lib/messages-v2/categories";
import type { MessageCategory, MessagePriority } from "@/lib/messages-v2/types";

const PRIORITY_TONE: Record<MessagePriority, string> = {
  Normal:    "bg-slate-50 text-slate-700 border-slate-200",
  Important: "bg-blue-50 text-blue-700 border-blue-200",
  Urgent:    "bg-amber-50 text-amber-800 border-amber-200",
  Critical:  "bg-rose-50 text-rose-700 border-rose-200",
};

export function MessagePriorityBadge({ priority, size = "sm" }: { priority: MessagePriority; size?: "xs" | "sm" }) {
  const Icon = PRIORITY_ICON[priority];
  if (priority === "Normal") return null; // calm — don't badge normal traffic
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border font-extrabold uppercase tracking-[0.06em]",
        PRIORITY_TONE[priority],
        size === "xs"
          ? "px-1.5 py-[1px] text-[9.5px]"
          : "px-2 py-[2px] text-[10px]",
      )}
    >
      <Icon size={size === "xs" ? 9 : 11} />
      {priority}
    </span>
  );
}

export function MessageCategoryBadge({ category, size = "sm" }: { category: MessageCategory; size?: "xs" | "sm" | "md" }) {
  const meta = categoryMeta(category);
  const Icon = meta.Icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border font-extrabold uppercase tracking-[0.06em]",
        meta.chip,
        size === "xs" ? "px-1.5 py-[1px] text-[9.5px]" :
        size === "md" ? "px-2.5 py-[3px] text-[11px]" :
                         "px-2 py-[2px] text-[10px]",
      )}
    >
      <Icon size={size === "xs" ? 9 : size === "md" ? 12 : 10} />
      {meta.label}
    </span>
  );
}

// Compact kind dot + label — used inside list rows beside the role pill.
export function MessageCategoryDot({ category }: { category: MessageCategory }) {
  const meta = categoryMeta(category);
  return (
    <span className="inline-flex items-center gap-1 text-caption text-[var(--color-edify-muted)] font-semibold">
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </span>
  );
}
