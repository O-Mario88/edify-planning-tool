"use client";

import { cn } from "@/lib/utils";
import type { BeMyPlanPeriod } from "@/lib/api/surfaces";

const PERIODS: { id: BeMyPlanPeriod; label: string }[] = [
  { id: "week", label: "This Week" },
  { id: "month", label: "This Month" },
  { id: "quarter", label: "This Quarter" },
  { id: "fy", label: "Fiscal Year" },
];

export function MyPlanPeriodTabs({
  value,
  onChange,
}: {
  value: BeMyPlanPeriod;
  onChange: (p: BeMyPlanPeriod) => void;
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 p-1">
      {PERIODS.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => onChange(p.id)}
          className={cn(
            "rounded-lg px-3 py-1.5 text-[11.5px] font-extrabold transition-colors",
            value === p.id
              ? "bg-white text-[var(--color-edify-primary)] shadow-sm border border-[var(--color-edify-border)]"
              : "text-slate-600 hover:bg-white/60",
          )}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
