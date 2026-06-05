"use client";

import { replicaKpis, type ReplicaKpi } from "@/lib/core-school-replica-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// 7 Core-School KPIs as one dense MetricStrip. Every meaningful KPI stays a
// clickable filter trigger that drills the page to the subset behind the
// number (active cell is highlighted); the per-tile mini-charts were dropped.

const KPI_FILTER_ID: Record<string, string | undefined> = {
  total:      "total",
  assessed:   "ssa-complete",
  avg_ssa:    "avg-ssa",
  on_track:   "on-track",
  behind:     "behind-schedule",
  critical:   "critical-gap",
  salesforce: "salesforce-compliance",
};

export function ReplicaKpiRow({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  const metrics: MetricCell[] = replicaKpis.map((k: ReplicaKpi) => {
    const filterId = KPI_FILTER_ID[k.key];
    return {
      key: k.key,
      label: k.label,
      value: k.value,
      unit: k.subValue,
      delta: k.delta ? { dir: k.deltaTone === "up" ? "up" : "down", text: `${k.delta}${k.caption ? ` ${k.caption}` : ""}` } : undefined,
      caption: !k.delta ? k.caption : undefined,
      active: !!filterId && activeFilterId === filterId,
      onClick: filterId && onTileClick ? () => onTileClick(filterId) : undefined,
    };
  });
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7" />;
}
