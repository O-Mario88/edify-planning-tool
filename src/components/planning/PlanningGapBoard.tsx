// PlanningGapBoard — the single, tabbed entry to gap-based planning.
//
// Three pill tabs (Client Schools · Clusters · Core Schools) switch
// between the three neat, collapsible gap boards. Each board groups its
// gaps into collapsible buckets, and every row expands inline to the
// detail a planner needs to make the right call — facts (contact, weak
// SSA areas, CCEO/partner), the recommended next action, and the action
// buttons themselves.
//
// Partner Assignments is intentionally NOT a tab here: once a partner has
// planned a school it is no longer an open gap — it lives under
// PlanningOwnershipSections ("Assigned to Partner" / "Awaiting Partner
// Schedule") / My Plan, not in the planning gap queue.

"use client";

import { useState } from "react";
import { Building2, UsersRound, Briefcase, type LucideIcon } from "lucide-react";
import { SchoolGapsBoard } from "./SchoolGapsBoard";
import { ClusterGapsBoard } from "./ClusterGapsBoard";
import { CorePlanningAccordion } from "@/components/core/CorePlanningAccordion";
import type { SlotViewer } from "@/components/core/CoreSlotActions";
import type { CorePlanCardVM } from "@/lib/core/core-board";
import type { SchoolGap, ClusterGap } from "@/lib/planning/planning-gaps-mock";
import { cn } from "@/lib/utils";

// Narrow an arbitrary role string to the assign drawer's recognised set.
type AssignRole = "CCEO" | "CountryProgramLead" | "ImpactAssessment" | "CountryDirector" | "Admin";
function normalizeRole(role?: string): AssignRole {
  return role === "CCEO" || role === "ImpactAssessment" || role === "CountryDirector" || role === "Admin"
    ? role
    : "CountryProgramLead";
}

type TabKey = "clientSchools" | "clusters" | "coreSchools";

type TabDef = { key: TabKey; label: string; icon: LucideIcon };

const TABS: ReadonlyArray<TabDef> = [
  { key: "clientSchools", label: "Client Schools", icon: Building2 },
  { key: "clusters", label: "Clusters", icon: UsersRound },
  { key: "coreSchools", label: "Core Schools", icon: Briefcase },
];

export function PlanningGapBoard({
  assigningUserRole,
  extraGaps = [],
  liveGaps = false,
  clusterGaps,
  liveClusterGaps = false,
  coreCards = [],
  coreGaps = [],
  liveCoreGaps = false,
  coreViewer = { canAssign: false, canExec: false, canIa: false },
  canChampion = false,
}: {
  /** Viewer's role — gates the assign drawer (CCEO→Partner; PL→CCEO/Partner). */
  assigningUserRole?: string;
  extraGaps?: SchoolGap[];
  /** True when extraGaps are REAL backend schools — suppress the seed mock and
   *  use the live writer for scheduling. */
  liveGaps?: boolean;
  clusterGaps?: ClusterGap[];
  /** True when clusterGaps are REAL backend clusters — schedule via the live writer. */
  liveClusterGaps?: boolean;
  coreCards?: CorePlanCardVM[];
  /** Backend core-school gaps — when live, the Core Schools tab uses the same
   *  detail-rich SchoolGapsBoard as Client Schools. */
  coreGaps?: SchoolGap[];
  liveCoreGaps?: boolean;
  coreViewer?: SlotViewer;
  canChampion?: boolean;
} = {}) {
  const [activeTab, setActiveTab] = useState<TabKey>("clientSchools");

  return (
    <section className="flex flex-col gap-3 md:gap-4" aria-label="Planning gaps">
      {/* Pill tabs — the one switcher for all gap planning. */}
      <div
        className="card rounded-xl p-1.5 flex items-center gap-1 overflow-x-auto"
        role="tablist"
        aria-label="Planning gap categories"
      >
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "relative inline-flex items-center gap-2 px-3.5 py-2 rounded-lg",
                "text-[12.5px] font-semibold whitespace-nowrap transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/40",
                isActive
                  ? "bg-[var(--color-edify-primary)] text-white shadow-sm"
                  : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
              )}
            >
              <Icon size={14} aria-hidden />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Active board — each renders its own collapsible, detail-rich card. */}
      <div role="tabpanel" aria-label={`${TABS.find((t) => t.key === activeTab)?.label} gaps`}>
        {activeTab === "clientSchools" && <SchoolGapsBoard assigningUserRole={normalizeRole(assigningUserRole)} extraGaps={extraGaps} liveGaps={liveGaps} />}
        {activeTab === "clusters" && <ClusterGapsBoard assigningUserRole={normalizeRole(assigningUserRole)} gaps={clusterGaps} liveGaps={liveClusterGaps} />}
        {activeTab === "coreSchools" && (
          liveCoreGaps
            ? <SchoolGapsBoard assigningUserRole={normalizeRole(assigningUserRole)} extraGaps={coreGaps} liveGaps boardKind="core" />
            : <CorePlanningAccordion cards={coreCards} viewer={coreViewer} canChampion={canChampion} />
        )}
      </div>
    </section>
  );
}

export default PlanningGapBoard;
