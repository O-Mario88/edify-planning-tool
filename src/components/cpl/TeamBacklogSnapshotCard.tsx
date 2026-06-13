"use client";

import { Layers } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { type BacklogSnapshotTile } from "@/lib/cpl-mock";
import { deriveTeamBacklog } from "@/lib/cpl-engine";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// Status-color discipline: rose-family tones (red/rose/lavender) read as
// critical → "alert"; amber-family (amber/blue/violet) read as pending →
// default. A rising backlog delta (deltaTone "up") is bad, so it maps to
// the strip's "down" (rose) trend color to preserve the original semantics.
const VALUE_TONE: Record<BacklogSnapshotTile["tone"], MetricCell["tone"]> = {
  amber:    "default",
  red:      "alert",
  blue:     "default",
  violet:   "default",
  rose:     "alert",
  lavender: "alert",
};

export function TeamBacklogSnapshotCard() {
  // Tiles derive from the team rollup (cceoPerformance × engine) so a
  // change to any CCEO's risk / backlog / SF-pending number propagates
  // here without UI changes.
  const tiles = deriveTeamBacklog();
  const metrics: MetricCell[] = tiles.map((r) => ({
    key: r.key,
    label: r.label,
    value: r.value,
    tone: VALUE_TONE[r.tone],
    // A rising backlog (deltaTone "up") is bad → red trend; map to "down".
    delta: { dir: r.deltaTone === "up" ? "down" : "up", text: r.delta },
  }));
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
      <MetricStrip bare columns="grid-cols-2 md:grid-cols-3 lg:grid-cols-6" metrics={metrics} />
    </SectionCard>
  );
}
