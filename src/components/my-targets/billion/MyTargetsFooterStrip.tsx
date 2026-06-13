"use client";

import { MetricStrip } from "@/components/ui/MetricStrip";
import { footerMetrics } from "@/lib/my-targets-billion-mock";

// Footer mini-metrics strip — seven tiny stats anchored to the bottom
// of the page, so high-frequency lookups (Verified count, Last Sync,
// Pending Salesforce) are always one glance away no matter how far
// the user scrolled.
export function MyTargetsFooterStrip() {
  return (
    <MetricStrip
      columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-7"
      metrics={footerMetrics.map((m) => ({
        key: m.key,
        label: m.label,
        value: m.value,
        caption: m.caption,
        tone: m.key === "last_sync" ? "good" : "default",
      }))}
    />
  );
}
