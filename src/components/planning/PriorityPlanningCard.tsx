"use client";

import { Info } from "lucide-react";
import { priorityPlanning, type PriorityPlanningRow, type Urgency } from "@/lib/planning-mock";
import { cn } from "@/lib/utils";

const urgencyClass = (u: Urgency) =>
  u === "Urgent" ? "chip-red" : u === "High" ? "chip-amber" : "chip-amber";

const severityClass = (tone: PriorityPlanningRow["severity"]["tone"]) =>
  tone === "red"
    ? "text-[var(--color-danger)]"
    : tone === "amber"
      ? "text-[var(--color-edify-orange)]"
      : "text-[#b45309]";

export function PriorityPlanningCard() {
  return (
    <div className="card col-span-12 md:col-span-3 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-body-lg font-bold">Schools Needing Priority Planning</h3>
          <Info size={13} className="text-[var(--color-edify-muted)]" />
        </div>
        <a
          className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
          href="/notifications"
        >
          View All
        </a>
      </div>

      <div className="space-y-2.5">
        {priorityPlanning.map((p) => (
          <div
            key={p.rank}
            className="rounded-xl border border-[var(--color-edify-border)] p-3 bg-white hover:bg-[var(--color-edify-soft)]/40"
          >
            <div className="flex items-start gap-3">
              <div
                className="w-7 h-7 rounded-md text-white text-[13px] font-extrabold grid place-items-center shrink-0"
                style={{ background: "var(--color-edify-primary)" }}
              >
                {p.rank}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[13px] font-bold leading-tight truncate">
                    {p.school}
                  </div>
                  <span className={cn("chip shrink-0", urgencyClass(p.urgency))}>
                    {p.urgency === "Urgent" ? "⚠ " : ""}{p.urgency}
                  </span>
                </div>

                <div className="text-[11.5px] muted mt-1 flex items-center gap-2 flex-wrap">
                  <span>{p.ssaScore}</span>
                  <span className={cn("font-semibold", severityClass(p.severity.tone))}>
                    {p.severity.label}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  {p.chips.map((c) => (
                    <span key={c} className="chip chip-grey">
                      {c}
                    </span>
                  ))}
                </div>

                <div className="text-[11.5px] mt-2 leading-tight">
                  <div>
                    <span className="muted">Weakest: </span>
                    <span className="font-semibold">{p.weakest}</span>
                  </div>
                  <div>
                    <span className="muted">Recommended: </span>
                    <span className="font-semibold">{p.recommended}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
