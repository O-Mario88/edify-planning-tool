// Pill — the design-system primitive for every status/badge/chip.
//
// Before this lived, the app had four different pill implementations
// (operating-targets, partners, today agenda, today cluster partners)
// and the eye read them as four different concepts when they were
// the same concept. This file is the single source of truth for
// status visuals.
//
// Use the convenience `<StatusPill kind="health">` for the standard
// health/track ladder, or `<Pill tone="success">` for ad-hoc cases.

import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type PillTone =
  | "success"   // green — On Track / Active / Certified
  | "warning"   // amber — At Risk / Pending / Behind
  | "danger"    // rose  — Off Track / Critical / Overdue
  | "info"      // blue  — In Progress / Planned (active)
  | "neutral"   // slate — Not Started / Offline / Default
  | "violet"    // accent — Champion / Featured
  | "amber";    // soft   — alternate warning when used near `warning`

export type PillSize = "xs" | "sm" | "md";

const TONE: Record<PillTone, { bg: string; text: string; border: string; dot: string }> = {
  success: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
  warning: { bg: "bg-amber-50",   text: "text-amber-700",   border: "border-amber-200",   dot: "bg-amber-500"   },
  danger:  { bg: "bg-rose-50",    text: "text-rose-700",    border: "border-rose-200",    dot: "bg-rose-500"    },
  info:    { bg: "bg-blue-50",    text: "text-blue-700",    border: "border-blue-200",    dot: "bg-blue-500"    },
  neutral: { bg: "bg-slate-100",  text: "text-slate-600",   border: "border-slate-200",   dot: "bg-slate-400"   },
  violet:  { bg: "bg-violet-50",  text: "text-violet-700",  border: "border-violet-200",  dot: "bg-violet-500"  },
  amber:   { bg: "bg-amber-100",  text: "text-amber-800",   border: "border-amber-300",   dot: "bg-amber-600"   },
};

const SIZE: Record<PillSize, { h: string; px: string; text: string; gap: string }> = {
  xs: { h: "h-[18px]", px: "px-1.5", text: "text-[10px]",   gap: "gap-1"    },
  sm: { h: "h-[22px]", px: "px-2",   text: "text-[11px]",   gap: "gap-1.5"  },
  md: { h: "h-[26px]", px: "px-2.5", text: "text-[12px]",   gap: "gap-1.5"  },
};

export type PillProps = {
  tone:      PillTone;
  size?:     PillSize;
  /** Show a leading colored dot (preferred over icon for lightweight status). */
  dot?:      boolean;
  /** Show a leading icon (preferred over dot when the icon adds meaning). */
  icon?:     LucideIcon;
  /** Use a softer, borderless treatment — good for inline chips inside
   *  dense tables where a border would add visual noise. */
  subtle?:   boolean;
  className?: string;
  children:  React.ReactNode;
};

export function Pill({
  tone,
  size = "sm",
  dot = false,
  icon: Icon,
  subtle = false,
  className,
  children,
}: PillProps) {
  const t = TONE[tone];
  const s = SIZE[size];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-semibold whitespace-nowrap",
        s.h, s.px, s.text, s.gap,
        t.bg, t.text,
        subtle ? "" : `border ${t.border}`,
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", t.dot)} />}
      {Icon && <Icon size={size === "xs" ? 9 : size === "sm" ? 10 : 12} className="shrink-0" />}
      {children}
    </span>
  );
}

// ────────── Convenience: standard status ladders ──────────

export type HealthStatus = "On Track" | "At Risk" | "Off Track" | "Not Started";
export type TaskStatus   = "Completed" | "In Progress" | "Planned" | "Overdue";

const HEALTH_TONE: Record<HealthStatus, PillTone> = {
  "On Track":    "success",
  "At Risk":     "warning",
  "Off Track":   "danger",
  "Not Started": "neutral",
};

const TASK_TONE: Record<TaskStatus, PillTone> = {
  "Completed":   "success",
  "In Progress": "info",
  "Planned":     "neutral",
  "Overdue":     "danger",
};

/** Standard project-health pill. Use this everywhere a metric is
 *  classified On Track / At Risk / Off Track / Not Started. */
export function HealthPill({
  status,
  size = "sm",
  withDot = true,
  className,
}: {
  status:     HealthStatus;
  size?:      PillSize;
  withDot?:   boolean;
  className?: string;
}) {
  return (
    <Pill tone={HEALTH_TONE[status]} size={size} dot={withDot} className={className}>
      {status}
    </Pill>
  );
}

/** Standard task-status pill. Use this in agendas, todo lists, and
 *  anywhere a row carries Completed / In Progress / Planned / Overdue. */
export function TaskPill({
  status,
  size = "sm",
  withDot = false,
  icon,
  className,
}: {
  status:     TaskStatus;
  size?:      PillSize;
  withDot?:   boolean;
  icon?:      LucideIcon;
  className?: string;
}) {
  return (
    <Pill tone={TASK_TONE[status]} size={size} dot={withDot} icon={icon} className={className}>
      {status}
    </Pill>
  );
}
