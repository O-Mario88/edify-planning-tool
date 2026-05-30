"use client";

// Below-the-fold tabs surface for the CPL dashboard.
//
// The page above the fold is reserved for the 60-second hero, KPI strip,
// Leadership Attention, Approval Queue, and CCEO Performance — the
// things a CPL must see before they act. Everything else (engine
// rollups, queues, field intelligence, finance) sits behind a tab here
// so the page reads as 5 hero sections + 1 deep-dive surface instead
// of 17 stacked sections.
//
// Tabs:
//   • Pipeline   — Approval queue depth, schools needing SSA, training
//                  follow-up overdue, team backlog.
//   • Quality    — SSA cluster intelligence, leaderboard, top performer,
//                  client SSA verification.
//   • Field      — CPL personal field work, leave & holiday impact,
//                  smart route & capacity.
//   • Finance    — Funding & execution, annual cycle.
//   • Reports    — Daily debriefs, team targets.

import { useState, type ReactNode } from "react";
import {
  Layers,
  ShieldCheck,
  Footprints,
  Wallet,
  FileText,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type TabKey = "pipeline" | "quality" | "field" | "finance" | "reports";

const TABS: Array<{ key: TabKey; label: string; Icon: LucideIcon; helper: string }> = [
  { key: "pipeline", label: "Pipeline",  Icon: Layers,      helper: "Approvals, SSA refresh, training follow-up, backlog." },
  { key: "quality",  label: "Quality",   Icon: ShieldCheck, helper: "SSA intelligence, leaderboard, verification." },
  { key: "field",    label: "Field",     Icon: Footprints,  helper: "Your field work, route, leave, capacity." },
  { key: "finance",  label: "Finance",   Icon: Wallet,      helper: "Funding utilization, annual cycle, approvals." },
  { key: "reports",  label: "Reports",   Icon: FileText,    helper: "Team debriefs, weekly intelligence." },
];

export function CplBelowFoldTabs({
  pipeline,
  quality,
  field,
  finance,
  reports,
}: {
  pipeline: ReactNode;
  quality:  ReactNode;
  field:    ReactNode;
  finance:  ReactNode;
  reports:  ReactNode;
}) {
  const [active, setActive] = useState<TabKey>("pipeline");
  const panel: Record<TabKey, ReactNode> = { pipeline, quality, field, finance, reports };
  const helper = TABS.find((t) => t.key === active)?.helper ?? "";

  return (
    <section className="card rounded-2xl overflow-hidden">
      <div className="flex items-end justify-between gap-3 px-3 pt-3 flex-wrap">
        <div
          role="tablist"
          aria-label="Country Program Lead — supplementary surfaces"
          className="flex items-center gap-1 flex-wrap"
        >
          {TABS.map(({ key, label, Icon }) => {
            const isActive = key === active;
            return (
              <button
                key={key}
                role="tab"
                type="button"
                aria-selected={isActive}
                aria-controls={`cpl-tab-panel-${key}`}
                id={`cpl-tab-${key}`}
                onClick={() => setActive(key)}
                className={cn(
                  "h-9 px-3 rounded-lg text-[var(--text-body)] font-semibold inline-flex items-center gap-1.5 transition-colors",
                  isActive
                    ? "bg-[var(--color-edify-primary)] text-white"
                    : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
                )}
              >
                <Icon size={13} />
                {label}
              </button>
            );
          })}
        </div>
        <p className="text-[var(--text-caption)] muted leading-snug max-w-[420px]">{helper}</p>
      </div>
      <div
        role="tabpanel"
        id={`cpl-tab-panel-${active}`}
        aria-labelledby={`cpl-tab-${active}`}
        className="p-3 sm:p-4 space-y-4 bg-[var(--color-edify-soft)]/30 border-t border-[var(--color-edify-border)] mt-3"
      >
        {panel[active]}
      </div>
    </section>
  );
}
