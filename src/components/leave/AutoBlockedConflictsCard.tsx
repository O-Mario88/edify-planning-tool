"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CalendarX,
  RotateCw,
  Users,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { autoBlockedConflicts, type AutoBlockedConflict } from "@/lib/leave-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<AutoBlockedConflict["icon"], LucideIcon> = {
  alertTriangle: AlertTriangle,
  calendarX:     CalendarX,
  rotate:        RotateCw,
  users:         Users,
};

const iconTone: Record<AutoBlockedConflict["icon"], string> = {
  alertTriangle: "bg-amber-100 text-amber-800",
  calendarX:     "bg-red-100 text-red-700",
  rotate:        "bg-blue-100 text-[#1e40af]",
  users:         "bg-violet-100 text-violet-700",
};

const actionStyle: Record<AutoBlockedConflict["action"], string> = {
  View:              "btn-primary",
  Reassign:          "border border-[var(--color-edify-border)] bg-white",
  "Auto-reschedule": "border border-[var(--color-edify-border)] bg-white",
};

export function AutoBlockedConflictsCard() {
  return (
    <SectionCard
      title="Auto-Blocked Conflicts"
      actions={
        <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/alerts">
          View All
        </Link>
      }
    >
      <div className="space-y-2.5">
        {autoBlockedConflicts.map((c) => {
          const Icon = iconMap[c.icon];
          return (
            <div
              key={c.id}
              className="flex items-start gap-3 px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)]"
            >
              <span className={cn("w-9 h-9 rounded-md grid place-items-center shrink-0", iconTone[c.icon])}>
                <Icon size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-semibold leading-tight">{c.title}</div>
                <div className="text-[11px] muted mt-0.5">{c.detail}</div>
              </div>
              <button
                type="button"
                className={cn(
                  "h-7 px-2.5 rounded-md text-[11.5px] font-semibold shrink-0",
                  actionStyle[c.action],
                )}
              >
                {c.action}
              </button>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}
