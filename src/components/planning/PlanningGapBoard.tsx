// PlanningGapBoard — top-level container for the SSA-gated, gap-based
// Planning Tool view. Renders a four-tab interface (Client Schools,
// Clusters, Core Schools, Partner Assignments) above a grid of
// PlanningGapCard atoms.
//
// This board is intentionally read-only at this phase: onAction simply
// logs to the console. Real routing — opening the schedule drawer,
// pushing into MyPlan, assigning to partner — is wired in a later
// integration phase.

"use client";

import { useState, useMemo } from "react";
import {
  Lock,
  Sparkles,
  Users,
  CalendarCheck,
  Building2,
  UsersRound,
  Briefcase,
  Handshake,
} from "lucide-react";
import { planningTabs } from "@/lib/planning/gap-mock";
import { PlanningGapCard } from "@/components/planning/PlanningGapCard";
import type {
  PlanningGap,
  PlanningActionKind,
} from "@/lib/planning/gap-types";
import { cn } from "@/lib/utils";

// ─── Tab definitions ──────────────────────────────────────────────

type TabKey = "clientSchools" | "clusters" | "coreSchools" | "partnerAssignments";

type TabDef = {
  key: TabKey;
  label: string;
  icon: typeof Building2;
};

const TABS: ReadonlyArray<TabDef> = [
  { key: "clientSchools",      label: "Client Schools",      icon: Building2 },
  { key: "clusters",           label: "Clusters",            icon: UsersRound },
  { key: "coreSchools",        label: "Core Schools",        icon: Briefcase },
  { key: "partnerAssignments", label: "Partner Assignments", icon: Handshake },
];

// ─── Health strip tile ────────────────────────────────────────────

type HealthTileProps = {
  label: string;
  value: number;
  icon: typeof Lock;
  tone: "rose" | "emerald" | "indigo" | "amber";
};

const TONE_CLASS: Record<HealthTileProps["tone"], string> = {
  rose:    "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  emerald: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  indigo:  "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  amber:   "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
};

function HealthTile({ label, value, icon: Icon, tone }: HealthTileProps) {
  return (
    <div className="card rounded-xl p-4 flex items-center gap-3">
      <span
        className={cn(
          "w-10 h-10 rounded-full flex items-center justify-center shrink-0",
          TONE_CLASS[tone],
        )}
        aria-hidden
      >
        <Icon size={18} />
      </span>
      <div className="flex flex-col">
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] muted">
          {label}
        </span>
        <span className="currency-display text-[22px] font-extrabold tabular leading-none mt-0.5 text-[var(--color-edify-text)]">
          {value}
        </span>
      </div>
    </div>
  );
}

// ─── Component ─────────────────────────────────────────────────────

export function PlanningGapBoard() {
  const [activeTab, setActiveTab] = useState<TabKey>("clientSchools");

  const tabCounts = useMemo<Record<TabKey, number>>(
    () => ({
      clientSchools:      planningTabs.clientSchools.length,
      clusters:           planningTabs.clusters.length,
      coreSchools:        planningTabs.coreSchools.length,
      partnerAssignments: planningTabs.partnerAssignments.length,
    }),
    [],
  );

  const activeGaps: PlanningGap[] = planningTabs[activeTab];

  const handleAction = (kind: PlanningActionKind, gap: PlanningGap) => {
    // Placeholder: real routing arrives in a later phase. Logging keeps
    // the contract observable in the dev console without surfacing a
    // half-built drawer to the user.
    // eslint-disable-next-line no-console
    console.log("[PlanningGapBoard] action", kind, gap.id);
  };

  return (
    <section
      className="flex flex-col gap-5"
      aria-label="SSA-gated Planning gaps"
    >
      {/* ── Section heading ── */}
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-[18px] font-bold leading-tight text-[var(--color-edify-text)] flex items-center gap-2">
            <Sparkles size={16} className="text-[var(--color-edify-primary)]" aria-hidden />
            Planning Gaps
          </h2>
          <p className="text-[12.5px] muted mt-0.5 max-w-xl">
            SSA-gated planning queue. Cards stay visible until the gap is
            resolved upstream (SSA completed, visit scheduled, partner
            assigned).
          </p>
        </div>
      </header>

      {/* ── Health strip ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <HealthTile
          label="SSA Locked"
          value={planningTabs.totals.ssaLocked}
          icon={Lock}
          tone="rose"
        />
        <HealthTile
          label="Ready to Plan"
          value={planningTabs.totals.readyToPlan}
          icon={Sparkles}
          tone="emerald"
        />
        <HealthTile
          label="Assigned to Partner"
          value={planningTabs.totals.assignedToPartner}
          icon={Users}
          tone="indigo"
        />
        <HealthTile
          label="Moved to MyPlan"
          value={planningTabs.totals.movedToMyPlan}
          icon={CalendarCheck}
          tone="amber"
        />
      </div>

      {/* ── Tabs ── */}
      <div
        className="card rounded-xl p-1.5 flex items-center gap-1 overflow-x-auto"
        role="tablist"
        aria-label="Planning gap categories"
      >
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const count = tabCounts[tab.key];
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
              <span
                className={cn(
                  "inline-flex items-center justify-center min-w-[20px] h-[20px] px-1.5",
                  "text-[10.5px] font-bold rounded-full tabular",
                  isActive
                    ? "bg-white/20 text-white"
                    : "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]",
                )}
                aria-label={`${count} gaps`}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── Active tab grid ── */}
      {activeGaps.length === 0 ? (
        <div
          className="card rounded-xl p-8 text-center"
          role="status"
        >
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300 mb-3">
            <Sparkles size={20} aria-hidden />
          </div>
          <h3 className="text-[14px] font-bold text-[var(--color-edify-text)]">
            No gaps in this tab
          </h3>
          <p className="text-[12.5px] muted mt-1">
            Every entity in this bucket is up to date.
          </p>
        </div>
      ) : (
        <div
          role="tabpanel"
          aria-label={`${TABS.find((t) => t.key === activeTab)?.label} gaps`}
          className={cn(
            "grid gap-4",
            "grid-cols-1",
            "lg:grid-cols-2",
            "2xl:grid-cols-3",
          )}
        >
          {activeGaps.map((gap) => (
            <PlanningGapCard
              key={gap.id}
              gap={gap}
              onAction={handleAction}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export default PlanningGapBoard;
