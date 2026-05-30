"use client";

// PlanningEmptyState — replaces the italic "No items found" lines that
// every tab and section used to ship. Empty states are a real product
// surface: they tell the user the system is working, explain *why*
// nothing is here, and suggest the next step.
//
// Variants:
//   • "calm"    — neutral surface, slate icon. Use when the filter
//                 simply has no matches and that's OK.
//   • "good"    — emerald surface, check icon. Use when "nothing here"
//                 is positive ("all schools have started their cycle").
//   • "blocked" — rose surface, lock icon. Use when the empty state is
//                 caused by a hard dependency the user must resolve.

import type { LucideIcon } from "lucide-react";
import { CheckCircle2, Inbox, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "calm" | "good" | "blocked";

const VARIANT_TONE: Record<Variant, { bg: string; ring: string; iconBg: string; iconText: string; Icon: LucideIcon; defaultEyebrow: string }> = {
  calm: {
    bg:       "bg-[var(--color-edify-soft)]/30",
    ring:     "ring-[var(--color-edify-divider)]",
    iconBg:   "bg-white",
    iconText: "text-[var(--color-edify-muted)]",
    Icon:     Inbox,
    defaultEyebrow: "Nothing to plan here",
  },
  good: {
    bg:       "bg-emerald-50/60",
    ring:     "ring-emerald-100",
    iconBg:   "bg-emerald-100",
    iconText: "text-emerald-700",
    Icon:     CheckCircle2,
    defaultEyebrow: "All clear",
  },
  blocked: {
    bg:       "bg-rose-50/60",
    ring:     "ring-rose-100",
    iconBg:   "bg-rose-100",
    iconText: "text-rose-700",
    Icon:     Lock,
    defaultEyebrow: "Blocked upstream",
  },
};

export function PlanningEmptyState({
  variant = "calm",
  title,
  body,
  eyebrow,
  size = "md",
}: {
  variant?: Variant;
  title:    string;
  body:     string;
  eyebrow?: string;
  size?:    "sm" | "md";
}) {
  const tone = VARIANT_TONE[variant];
  const Icon = tone.Icon;
  const isSmall = size === "sm";
  return (
    <div className={cn(
      "rounded-2xl ring-1 text-center",
      tone.bg, tone.ring,
      isSmall ? "px-4 py-6" : "px-5 py-8",
    )}>
      <div className="flex justify-center">
        <span className={cn(
          "grid place-items-center rounded-full ring-4 ring-white",
          tone.iconBg, tone.iconText,
          isSmall ? "h-9 w-9" : "h-11 w-11",
        )}>
          <Icon size={isSmall ? 15 : 18} />
        </span>
      </div>
      <div className={cn(
        "uppercase tracking-wider font-extrabold text-[var(--color-edify-muted)] mt-3",
        isSmall ? "text-[10px]" : "text-[10px]",
      )}>
        {eyebrow ?? tone.defaultEyebrow}
      </div>
      <h3 className={cn(
        "font-extrabold tracking-tight text-[var(--color-edify-text)] mt-1",
        isSmall ? "text-[13px]" : "text-body-lg",
      )}>
        {title}
      </h3>
      <p className={cn(
        "muted leading-snug mt-1 mx-auto",
        isSmall ? "text-[11px] max-w-[42ch]" : "text-[12px] max-w-[52ch]",
      )}>
        {body}
      </p>
    </div>
  );
}
