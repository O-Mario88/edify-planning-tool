"use client";

// Core planning workspace — switch between the gap-tab filter and the §14
// collapse/expand accordion. Both render the real CorePlanBoard underneath.

import { useState } from "react";
import { LayoutList, Rows3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { CoreGapTabs } from "./CoreGapTabs";
import { CorePlanningAccordion } from "./CorePlanningAccordion";
import type { SlotViewer } from "./CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";

export function CorePlanningWorkspace({ cards, viewer, canChampion }: { cards: CorePlanCardVM[]; viewer: SlotViewer; canChampion: boolean }) {
  const [view, setView] = useState<"sections" | "tabs">("sections");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Toggle active={view === "sections"} onClick={() => setView("sections")} icon={<Rows3 size={12} />} label="Sections" />
        <Toggle active={view === "tabs"} onClick={() => setView("tabs")} icon={<LayoutList size={12} />} label="Gap tabs" />
      </div>
      {view === "sections"
        ? <CorePlanningAccordion cards={cards} viewer={viewer} canChampion={canChampion} />
        : <CoreGapTabs cards={cards} viewer={viewer} canChampion={canChampion} />}
    </div>
  );
}

function Toggle({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button type="button" onClick={onClick}
      className={cn("inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-bold border",
        active ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]" : "border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40")}>
      {icon} {label}
    </button>
  );
}
