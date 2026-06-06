"use client";

// Core School Planning — grouped into sections (§14), each showing a compact
// LIST of schools. Clicking a SCHOOL row expands it inline to reveal the full
// plan detail (4+4 slots, follow-up SSA, impact, champion) with live controls.
// The expand/collapse unit is the SCHOOL, not the section.

import { useState } from "react";
import { ChevronDown, ChevronRight, ChevronUp, Footprints, GraduationCap, Trophy, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CorePlanBoard } from "./CorePlanBoard";
import type { SlotViewer } from "./CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";

type Section = { key: string; label: string; match: (c: CorePlanCardVM) => boolean };

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

function nextAction(c: CorePlanCardVM): string {
  if (c.plan.status === "Completed Pending Follow-Up SSA") return "Schedule Follow-Up SSA";
  if (c.plan.status === "Follow-Up SSA Scheduled") return "Awaiting Follow-Up SSA";
  if (c.progress.visitsCompleted < 4) return `Schedule Visit ${c.progress.visitsCompleted + 1}`;
  if (c.progress.trainingsCompleted < 4) return `Schedule Training ${c.progress.trainingsCompleted + 1}`;
  return "Measure impact";
}

// Icon per section group (visits / trainings / champion-or-done / follow-up).
function sectionIcon(key: string): LucideIcon {
  if (key.startsWith("t")) return GraduationCap;
  if (key === "potential" || key === "verified" || key === "fullpackage") return Trophy;
  return Footprints;
}

export function CorePlanningAccordion({ cards, viewer, canChampion }: { cards: CorePlanCardVM[]; viewer: SlotViewer; canChampion: boolean }) {
  const sections = SECTIONS.map((s) => ({ ...s, items: cards.filter(s.match) })).filter((s) => s.items.length > 0);

  // Section-level collapse (matches the Client Schools + Clusters gap boards):
  // click a card header to expand/collapse its whole list of schools. The "done"
  // buckets (full package complete, verified champions) start collapsed.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(SECTIONS.map((s) => [s.key, s.key === "fullpackage" || s.key === "verified"])),
  );

  if (cards.length === 0) {
    return <div className="card p-8 text-center text-[12px] muted italic">No core plans in your scope yet.</div>;
  }
  return (
    <div className="space-y-3">
      {sections.map((s) => {
        const isCollapsed = collapsed[s.key];
        const Icon = sectionIcon(s.key);
        return (
          <div key={s.key} className="rounded-xl border border-[var(--color-edify-divider)] bg-white">
            <button
              type="button"
              onClick={() => setCollapsed((c) => ({ ...c, [s.key]: !c[s.key] }))}
              aria-expanded={!isCollapsed}
              className="w-full flex items-center gap-3 px-3.5 py-2.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors text-left"
            >
              <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)]">
                <Icon size={14} />
              </span>
              <div className="flex-1 min-w-0 text-[12px] font-extrabold tracking-tight">{s.label}</div>
              <span className="text-[12px] font-extrabold tabular text-[var(--color-edify-text)]">{s.items.length}</span>
              <span className="text-[var(--color-edify-muted)]">
                {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </span>
            </button>
            {!isCollapsed && (
              <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
                {s.items.map((c) => <SchoolRow key={c.plan.id} c={c} viewer={viewer} canChampion={canChampion} />)}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SchoolRow({ c, viewer, canChampion }: { c: CorePlanCardVM; viewer: SlotViewer; canChampion: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2.5 py-2 hover:bg-[var(--color-edify-soft)]/30 text-left">
        {open ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />}
        <span className="font-bold text-[12px] truncate min-w-0 flex-1">{c.schoolName}
          <span className="muted font-normal"> · {c.district}{c.cluster ? ` · ${c.cluster}` : ""}</span>
        </span>
        <span className="hidden sm:inline-flex items-center gap-2 text-[10.5px] muted tabular shrink-0">
          <span className="inline-flex items-center gap-0.5"><Footprints size={10} />{c.progress.visitsCompleted}/4</span>
          <span className="inline-flex items-center gap-0.5"><GraduationCap size={10} />{c.progress.trainingsCompleted}/4</span>
          {c.championStatus !== "Not Eligible" && <span className="inline-flex items-center gap-0.5 text-amber-700"><Trophy size={10} />{c.championStatus}</span>}
        </span>
        <span className={cn("shrink-0 text-[10px] font-bold px-1.5 py-[2px] rounded-full hidden md:inline", open ? "bg-[var(--color-edify-primary)] text-white" : "bg-[var(--color-edify-soft)]/70")}>{nextAction(c)}</span>
      </button>
      {open && (
        <div className="px-2 pb-2 pt-1 border-t border-[var(--color-edify-divider)]">
          <CorePlanBoard cards={[c]} viewer={viewer} canChampion={canChampion} />
        </div>
      )}
    </li>
  );
}
