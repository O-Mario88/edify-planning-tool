"use client";

import { useState, type ReactNode } from "react";
import { Target, Users, AlertTriangle, RotateCcw, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// Tab strip that swaps the visible panel for /team-targets.
//
// Role drives the default tab:
//   • CCEO              → My Targets
//   • CountryProgramLead → Team Targets
//   • CountryDirector / RVP → Team Targets (treated as country/regional)
//
// Each tab's content is passed in as a prop slot — server-rendered cards
// stay server-rendered; the client only owns the tab state.

export type TeamTargetsTab =
  | "my"
  | "team"
  | "support"
  | "recovery";

const TABS: { key: TeamTargetsTab; label: string; Icon: LucideIcon }[] = [
  { key: "my",          label: "My Targets",       Icon: Target },
  { key: "team",        label: "Team Targets",     Icon: Users },
  { key: "support",     label: "Support Needed",   Icon: AlertTriangle },
  { key: "recovery",    label: "Target Recovery",  Icon: RotateCcw },
];

export function TeamTargetsTabs({
  defaultTab,
  myTargets,
  teamTargets,
  supportNeeded,
  targetRecovery,
}: {
  defaultTab: TeamTargetsTab;
  myTargets:      ReactNode;
  teamTargets:    ReactNode;
  supportNeeded:  ReactNode;
  targetRecovery: ReactNode;
}) {
  const [tab, setTab] = useState<TeamTargetsTab>(defaultTab);
  return (
    <>
      <div className="card rounded-2xl p-2 flex items-center gap-1 overflow-x-auto">
        {TABS.map(({ key, label, Icon }) => {
          const active = tab === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                "h-10 px-3 rounded-lg text-body font-extrabold tracking-tight inline-flex items-center gap-2 flex-1 justify-center whitespace-nowrap",
                active
                  ? "bg-[var(--color-edify-primary)] text-white"
                  : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              <Icon size={13} />
              <span className="hidden sm:inline">{label}</span>
            </button>
          );
        })}
      </div>
      <div className="mt-3 space-y-3 md:space-y-4">
        {tab === "my"          && myTargets}
        {tab === "team"        && teamTargets}
        {tab === "support"     && supportNeeded}
        {tab === "recovery"    && targetRecovery}
      </div>
    </>
  );
}
