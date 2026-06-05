"use client";

// Core School Planning accordion (§14) — collapsible sections derived from the
// real CorePlan progress. Default: expand the most urgent non-empty section,
// collapse the rest. Each section header shows a live count; the body is the
// real CorePlanBoard (full execution controls) for that section's plans.

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { CorePlanBoard } from "./CorePlanBoard";
import type { SlotViewer } from "./CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";

type Section = { key: string; label: string; match: (c: CorePlanCardVM) => boolean };

// Next-needed buckets: a plan lands in exactly one visit-section and one
// training-section (its next required), plus lifecycle sections.
const SECTIONS: Section[] = [
  { key: "ready", label: "Ready for Planning", match: (c) => c.progress.visitsCompleted === 0 && c.progress.trainingsCompleted === 0 && c.plan.status !== "Completed Pending Follow-Up SSA" },
  { key: "v1", label: "Missing Visit 1", match: (c) => c.progress.visitsCompleted === 0 },
  { key: "v2", label: "Missing Visit 2", match: (c) => c.progress.visitsCompleted === 1 },
  { key: "v3", label: "Missing Visit 3", match: (c) => c.progress.visitsCompleted === 2 },
  { key: "v4", label: "Missing Visit 4", match: (c) => c.progress.visitsCompleted === 3 },
  { key: "t1", label: "Missing Training 1", match: (c) => c.progress.trainingsCompleted === 0 },
  { key: "t2", label: "Missing Training 2", match: (c) => c.progress.trainingsCompleted === 1 },
  { key: "t3", label: "Missing Training 3", match: (c) => c.progress.trainingsCompleted === 2 },
  { key: "t4", label: "Missing Training 4", match: (c) => c.progress.trainingsCompleted === 3 },
  { key: "followup", label: "Follow-Up SSA Due", match: (c) => c.plan.status === "Completed Pending Follow-Up SSA" || c.plan.status === "Follow-Up SSA Scheduled" },
  { key: "fullpackage", label: "Full Core Package Complete", match: (c) => c.progress.visitsCompleted >= 4 && c.progress.trainingsCompleted >= 4 },
  { key: "potential", label: "Potential Champion Schools", match: (c) => c.championStatus === "Potential Champion" || c.championStatus === "Under Review" },
  { key: "verified", label: "Verified Champion Schools", match: (c) => c.championStatus === "Verified Champion" || c.championStatus === "Champion Mentor School" },
];

export function CorePlanningAccordion({ cards, viewer, canChampion }: { cards: CorePlanCardVM[]; viewer: SlotViewer; canChampion: boolean }) {
  const sections = useMemo(
    () => SECTIONS.map((s) => ({ ...s, items: cards.filter(s.match) })).filter((s) => s.items.length > 0),
    [cards],
  );
  // Default: expand the first (most urgent) non-empty section.
  const [open, setOpen] = useState<Record<string, boolean>>(() => (sections[0] ? { [sections[0].key]: true } : {}));

  if (cards.length === 0) {
    return <div className="card p-8 text-center text-[12px] muted italic">No core plans in your scope yet.</div>;
  }

  return (
    <div className="space-y-2">
      {sections.map((s) => {
        const isOpen = !!open[s.key];
        return (
          <section key={s.key} className="card overflow-hidden">
            <button type="button" onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
              className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 hover:bg-[var(--color-edify-soft)]/30">
              <span className="inline-flex items-center gap-2 text-[12.5px] font-extrabold tracking-tight">
                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {s.label}
                <span className={cn("tabular text-[11px] px-1.5 rounded-full", isOpen ? "bg-[var(--color-edify-primary)] text-white" : "bg-[var(--color-edify-soft)]/70")}>{s.items.length}</span>
              </span>
            </button>
            {isOpen && (
              <div className="px-3 pb-3 pt-1 border-t border-[var(--color-edify-divider)]">
                <CorePlanBoard cards={s.items} viewer={viewer} canChampion={canChampion} />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
