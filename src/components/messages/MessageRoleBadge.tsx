"use client";

import { cn } from "@/lib/utils";
import type { MessageSenderRole } from "@/lib/messages-v2/types";

const ROLE_TONE: Record<MessageSenderRole, string> = {
  "CCEO":             "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  "Program Lead":     "bg-violet-50 text-violet-700",
  "Country Director": "bg-orange-50 text-orange-700",
  "RVP":              "bg-indigo-50 text-indigo-700",
  "M&E":              "bg-emerald-50 text-emerald-700",
  "HR":               "bg-rose-50 text-rose-700",
  "Accountant":       "bg-amber-50 text-amber-700",
  "Partner":          "bg-cyan-50 text-cyan-700",
  "Admin":            "bg-slate-100 text-slate-700",
  "System":           "bg-slate-100 text-slate-600",
};

export function MessageRoleBadge({ role, size = "sm" }: { role: MessageSenderRole; size?: "xs" | "sm" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md font-extrabold uppercase tracking-[0.06em]",
        ROLE_TONE[role],
        size === "xs" ? "px-1.5 py-[1px] text-[9.5px]" : "px-2 py-[2px] text-[10px]",
      )}
    >
      {role.toUpperCase()}
    </span>
  );
}
