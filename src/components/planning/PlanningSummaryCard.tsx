"use client";

import {
  GraduationCap,
  EyeOff,
  Ban,
  CheckCircle2,
  CircleAlert,
  Building,
  Users,
} from "lucide-react";
import { planningSummary, planningFooter, type PlanningSummaryTile } from "@/lib/planning-mock";

const iconMap = {
  noTraining: GraduationCap,
  noVisit: EyeOff,
  neither: Ban,
  completed: CheckCircle2,
  notCompleted: CircleAlert,
  inactive: Building,
  active: Users,
} as const;

const toneStyle: Record<PlanningSummaryTile["tone"], { bg: string; fg: string }> = {
  amber:  { bg: "#fef3c7", fg: "#92400e" },
  red:    { bg: "#fee2e2", fg: "#b91c1c" },
  purple: { bg: "#ede9fe", fg: "#6d28d9" },
  green:  { bg: "#dcfce7", fg: "#166534" },
  orange: { bg: "#ffedd5", fg: "#9a3412" },
  grey:   { bg: "#e5e7eb", fg: "#374151" },
  edify:  { bg: "#eef4f7", fg: "#344f5f" },
};

export function PlanningSummaryCard() {
  return (
    <div className="card col-span-12 md:col-span-5 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="w-6 h-6 rounded-md flex items-center justify-center"
            style={{ background: "var(--color-edify-soft)", color: "var(--color-edify-primary)" }}
          >
            <CheckCircle2 size={13} />
          </span>
          <h3 className="text-body-lg font-bold">Planning Summary</h3>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {planningSummary.map((t) => {
          const Icon = iconMap[t.icon];
          const tone = toneStyle[t.tone];
          return (
            <div
              key={t.key}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex flex-col items-center text-center"
            >
              <div className="text-caption muted font-semibold leading-tight min-h-[26px] flex items-center">
                {t.label}
              </div>
              <div
                className="w-9 h-9 rounded-full grid place-items-center my-1"
                style={{ background: tone.bg, color: tone.fg }}
              >
                <Icon size={16} />
              </div>
              <div className="text-[18px] font-extrabold tabular leading-none">
                {t.value}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-2 text-[11.5px] muted">{planningFooter.note}</div>
    </div>
  );
}
