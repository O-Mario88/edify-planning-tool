"use client";

// Live Analytics Data-Room — replaces the old mock-computed FieldEngineAnalytics
// section in production. Every panel is a real, role-scoped, filter-aware backend
// surface (the same /analytics endpoints the rest of the page uses), so the
// data-room traces to source records — no placeholder numbers, no mock universe.

import { Database } from "lucide-react";
import { InterventionPerformanceCard } from "@/components/ssa/InterventionPerformanceCard";
import { InterventionImprovementGrid } from "@/components/ssa/InterventionImprovementGrid";

export function LiveDataRoom() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Database size={14} className="text-[var(--color-edify-primary)]" /> Analytics data-room
        </h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend · filter-aware</span>
      </div>

      {/* Performance in each of the 8 SSA interventions across the scope. */}
      <InterventionPerformanceCard />

      {/* SSA performance by district lives on the interactive map above (choropleth
          + per-district detail panel), so it's intentionally not duplicated here.
          District/region/CCEO/cluster grouping remains on the SSA Performance page. */}

      {/* Impact: previous-FY vs current-FY intervention movement. */}
      <InterventionImprovementGrid />
    </div>
  );
}
