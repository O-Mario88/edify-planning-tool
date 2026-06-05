"use client";

// Gap-tab workspace for the Core Planning Board (§10). Filters the real
// CorePlan cards by the open-work bucket the user selects — no dismiss
// overlays, the board still mutates the unified store. "All" shows everything.

import { useState } from "react";
import { cn } from "@/lib/utils";
import { CorePlanBoard } from "./CorePlanBoard";
import type { SlotViewer } from "./CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";
import { CORE_GAP_TABS, coreCardGaps, coreGapCounts, type CoreGapTab } from "@/lib/core/core-gaps";

export function CoreGapTabs({ cards, viewer, canChampion }: { cards: CorePlanCardVM[]; viewer: SlotViewer; canChampion: boolean }) {
  const [active, setActive] = useState<CoreGapTab | "All">("All");
  const counts = coreGapCounts(cards);
  const filtered = active === "All" ? cards : cards.filter((c) => coreCardGaps(c).includes(active));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <Tab label="All" count={cards.length} active={active === "All"} onClick={() => setActive("All")} />
        {CORE_GAP_TABS.map((t) => (
          <Tab key={t} label={t} count={counts[t]} active={active === t} onClick={() => setActive(t)} dim={counts[t] === 0} />
        ))}
      </div>
      {filtered.length === 0 ? (
        <div className="card p-8 text-center text-[12px] muted italic">No core plans in “{active}”.</div>
      ) : (
        <CorePlanBoard cards={filtered} viewer={viewer} canChampion={canChampion} />
      )}
    </div>
  );
}

function Tab({ label, count, active, onClick, dim }: { label: string; count: number; active: boolean; onClick: () => void; dim?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border transition-colors",
        active ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
          : dim ? "border-[var(--color-edify-divider)] muted opacity-60 hover:opacity-100"
          : "border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40")}>
      {label}
      <span className={cn("tabular text-[10px] px-1 rounded", active ? "bg-white/20" : "bg-[var(--color-edify-soft)]/70")}>{count}</span>
    </button>
  );
}
