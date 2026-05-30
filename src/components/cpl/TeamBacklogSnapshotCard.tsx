"use client";

import {
  Layers,
  Users,
  Database,
  Wallet,
  Building2,
  GraduationCap,
  AlertOctagon,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { type BacklogSnapshotTile } from "@/lib/cpl-mock";
import { deriveTeamBacklog } from "@/lib/cpl-engine";
import { cn } from "@/lib/utils";

const iconMap: Record<BacklogSnapshotTile["icon"], LucideIcon> = {
  users:         Users,
  database:      Database,
  wallet:        Wallet,
  schoolX:       Building2,
  graduationCap: GraduationCap,
  alertOctagon:  AlertOctagon,
};

// Status-color discipline: 4-tone semantic system. Backlog tiles use only
// `amber` (pending) and `rose` (critical). Source data tones of `blue`,
// `violet`, `red`, and `lavender` are mapped at render time below.
const toneFrame: Record<BacklogSnapshotTile["tone"], string> = {
  amber:    "bg-amber-100 text-amber-800",
  red:      "bg-rose-100 text-rose-700",
  blue:     "bg-amber-100 text-amber-800",
  violet:   "bg-amber-100 text-amber-800",
  rose:     "bg-rose-100 text-rose-700",
  lavender: "bg-rose-100 text-rose-700",
};

const valueColor: Record<BacklogSnapshotTile["tone"], string> = {
  amber:    "text-amber-800",
  red:      "text-rose-700",
  blue:     "text-amber-800",
  violet:   "text-amber-800",
  rose:     "text-rose-700",
  lavender: "text-rose-700",
};

export function TeamBacklogSnapshotCard() {
  // Tiles derive from the team rollup (cceoPerformance × engine) so a
  // change to any CCEO's risk / backlog / SF-pending number propagates
  // here without UI changes.
  const tiles = deriveTeamBacklog();
  return (
    <SectionCard
      icon={<Layers size={13} />}
      title="Team Targets & Backlog Snapshot"
      actions={
        <a className="text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]" href="#backlog-snapshot">
          View backlog analytics →
        </a>
      }
    >
      {/* 2 across on phones, 3 across at md, 6 across at lg+ when the
          card spans the full row width and each tile gets enough room
          for the label to read clean (no truncated "1 high-…" etc). */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 md:gap-2.5">
        {tiles.map((r, i) => {
          const Icon = iconMap[r.icon];
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <div
              key={r.key}
              className={cn(
                "card-elevated card-lift cursor-default tile-in p-2.5 overflow-hidden",
                staggerCls,
              )}
            >
              <div className={cn("w-7 h-7 rounded-md grid place-items-center shrink-0", toneFrame[r.tone])}>
                <Icon size={13} />
              </div>
              <div className={cn("text-[var(--text-h-sm)] font-extrabold tabular mt-1.5 leading-none truncate", valueColor[r.tone])}>
                {r.value}
              </div>
              <div className="text-[var(--text-caption)] muted font-semibold leading-tight mt-1">
                {r.label}
              </div>
              <div
                className={cn(
                  "text-[var(--text-tiny)] font-semibold mt-1 flex items-center gap-1 truncate",
                  r.deltaTone === "up"
                    ? "text-[var(--color-danger)]"
                    : "text-[var(--color-success)]",
                )}
              >
                {r.deltaTone === "up" ? <ArrowUpRight size={9} className="shrink-0" /> : <ArrowDownRight size={9} className="shrink-0" />}
                <span className="muted font-medium truncate">{r.delta}</span>
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}
