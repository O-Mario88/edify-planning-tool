"use client";

import Link from "next/link";
import { CheckCircle2, Clock } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { weeklyPacing } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  "On Track":         "text-emerald-700",
  "Slightly Behind":  "text-amber-700",
  "Behind":           "text-orange-700",
  "High Risk":        "text-rose-700",
  "Critical":         "text-rose-700",
};

export function WeeklyPacingCard() {
  const w = weeklyPacing;
  return (
    <SectionCard title="Weekly Pacing" subtitle={`${w.weekStart} – ${w.weekEnd}`}>
      <div className="space-y-2 text-body">
        <Row label="Completed This Week" value={w.completedThisWeek.toLocaleString()} bold />
        <Row label="Weekly Target"        value={w.weeklyTarget.toLocaleString()} />
        <Row label="Achievement"          value={`${w.achievementPercent}%`} bold />
        <div className="flex items-center justify-between">
          <span className="muted">Status</span>
          <span className={cn("text-[13px] font-extrabold", STATUS_TONE[w.status])}>{w.status}</span>
        </div>
      </div>

      <div className="mt-2 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--color-edify-orange)]"
          style={{ width: `${w.achievementPercent}%` }}
        />
      </div>

      <div className="mt-3 grid grid-cols-7 gap-1.5">
        {w.weekday.map((d) => (
          <div key={d.day} className="text-center">
            <div className="text-caption muted font-semibold">{d.day}</div>
            <div
              className={cn(
                "mt-1 h-9 rounded-md grid place-items-center text-[12px] font-bold tabular border",
                d.state === "complete"
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : d.state === "today"
                    ? "bg-[var(--color-edify-soft)] border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]"
                    : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
              )}
            >
              {d.date}
            </div>
            <div className="mt-1 grid place-items-center">
              {d.state === "complete" ? (
                <CheckCircle2 size={10} className="text-emerald-600" />
              ) : d.state === "today" ? (
                <Clock size={10} className="text-[var(--color-edify-primary)]" />
              ) : (
                <span className="w-1.5 h-1.5 rounded-full bg-[#cbd5d8] inline-block" />
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 text-right">
        <Link href="/calendar" className="text-[12px] font-semibold text-[var(--color-edify-primary)]">
          View full monthly planner →
        </Link>
      </div>
    </SectionCard>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="muted">{label}</span>
      <span className={cn("tabular", bold ? "font-extrabold text-[13px]" : "font-semibold")}>{value}</span>
    </div>
  );
}
