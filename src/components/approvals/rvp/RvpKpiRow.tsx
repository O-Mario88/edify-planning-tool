"use client";

import { rvpKpis } from "@/lib/rvp-fund-approvals-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// RVP fund-approval KPIs — one dense MetricStrip (the canonical app-wide
// KPI-row pattern; progress rings are intentionally dropped in the strip).
export function RvpKpiRow() {
  const metrics: MetricCell[] = rvpKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    delta: k.delta
      ? { dir: k.deltaTone === "down" ? "down" : "up", text: `${k.delta}${k.subValue ?? k.caption ? ` · ${k.subValue ?? k.caption}` : ""}` }
      : undefined,
    caption: !k.delta ? (k.subValue ?? k.caption) : undefined,
  }));
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
    </section>
  );
}
