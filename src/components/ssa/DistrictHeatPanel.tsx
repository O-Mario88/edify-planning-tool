"use client";

import { Map } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { districtHeatTiles, type PerformanceStatus } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const tileTone: Record<PerformanceStatus, string> = {
  Strong:   "bg-emerald-50 border-emerald-200",
  Fair:     "bg-amber-50 border-amber-200",
  Weak:     "bg-orange-50 border-orange-200",
  Critical: "bg-rose-50 border-rose-200",
};

const labelTone: Record<PerformanceStatus, string> = {
  Strong:   "text-emerald-700",
  Fair:     "text-amber-700",
  Weak:     "text-orange-700",
  Critical: "text-rose-700",
};

export function DistrictHeatPanel() {
  return (
    <SectionCard title="District Performance Heat Panel">
      <div className="grid grid-cols-2 gap-2">
        {districtHeatTiles.map((t) => (
          <div
            key={t.district}
            className={cn("rounded-xl border p-2.5 flex items-center gap-2", tileTone[t.status])}
          >
            <span className="w-9 h-9 rounded-md bg-white/70 grid place-items-center text-[var(--color-edify-muted)] shrink-0">
              <Map size={14} />
            </span>
            <div className="leading-tight min-w-0">
              <div className="text-[11px] muted font-semibold">{t.district}</div>
              <div className="text-[18px] font-extrabold tabular leading-none">
                {t.score.toFixed(2)}
              </div>
              <div className={cn("text-caption font-bold mt-0.5", labelTone[t.status])}>
                {t.status}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex flex-wrap items-center gap-x-3 gap-y-1.5 text-caption muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
          &lt; 4.0
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-orange-500" />
          4.0 – 6.0
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
          6.0 – 7.5
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
          &gt; 7.5
        </span>
      </div>
    </SectionCard>
  );
}
