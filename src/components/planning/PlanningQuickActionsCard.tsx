"use client";

import { CalendarPlus, CalendarDays, Star, MapPin, Send, Zap } from "lucide-react";
import { quickActions } from "@/lib/planning-mock";
import { cn } from "@/lib/utils";

const iconMap = {
  calendarPlus: CalendarPlus,
  calendarDays: CalendarDays,
  starCheck: Star,
  mapPin: MapPin,
  send: Send,
} as const;

export function PlanningQuickActionsCard({
  onScheduleLeave,
}: {
  onScheduleLeave?: () => void;
} = {}) {
  return (
    <div className="card col-span-12 md:col-span-4 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span
          className="w-6 h-6 rounded-md flex items-center justify-center"
          style={{ background: "var(--color-edify-soft)", color: "var(--color-edify-primary)" }}
        >
          <Zap size={13} />
        </span>
        <h3 className="text-body-lg font-bold">Planning Quick Actions</h3>
      </div>

      {/* Responsive grid — 5 tiles: top row 3, bottom row 2 centred,
          or a single 5-col strip on wider cards. The auto-fit min
          guarantees at least 72px per tile so labels never clip. */}
      <div className="grid grid-cols-3 gap-2">
        {quickActions.map((a) => {
          const Icon = iconMap[a.icon];
          const isLeave = a.key === "leave";
          return (
            <button
              key={a.key}
              onClick={isLeave && onScheduleLeave ? onScheduleLeave : undefined}
              className={cn(
                "rounded-xl border p-3 flex flex-col items-center text-center transition-colors",
                a.primary
                  ? "border-transparent text-white"
                  : isLeave
                    ? "border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/60 hover:bg-[var(--color-edify-soft)]"
                    : "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60",
              )}
              style={
                a.primary
                  ? { background: "var(--color-edify-primary)" }
                  : undefined
              }
            >
              <span
                className={cn(
                  "w-9 h-9 rounded-full grid place-items-center mb-1.5",
                  a.primary
                    ? "bg-white/15 text-white"
                    : isLeave
                      ? "bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)]"
                      : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
                )}
              >
                <Icon size={16} />
              </span>
              <span className="text-[11.5px] font-bold leading-tight">
                {a.label.line1}
              </span>
              <span
                className={cn(
                  "text-[11.5px] font-bold leading-tight",
                  a.primary ? "text-white" : "",
                )}
              >
                {a.label.line2}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
