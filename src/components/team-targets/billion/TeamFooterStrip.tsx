"use client";

import { MetricStrip } from "@/components/ui/MetricStrip";
import { teamFooterMetrics } from "@/lib/team-targets-billion-mock";

// Footer mini-metrics strip — 7 team-level stats anchored at the
// bottom of the page so high-frequency lookups (verified activities,
// open support reviews, last sync) are always one glance away.
export function TeamFooterStrip() {
  return (
    <MetricStrip
      columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-7"
      metrics={teamFooterMetrics.map((m) => ({
        key: m.key,
        label: m.label,
        value: m.value,
        caption: m.caption,
        tone: m.key === "last_sync" ? "good" : "default",
      }))}
    />
  );
}
