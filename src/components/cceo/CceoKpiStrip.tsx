"use client";

import { AlertOctagon, CheckCircle2, Clock, Gauge, School } from "lucide-react";
import { cceoKpis } from "@/lib/cceo-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// CCEO SSA + health strip — flattened to the dense MetricStrip so every
// dashboard speaks one KPI format. The old hero panel (SSA sparkline + the
// segmented health funnel) is dropped in favour of flush cells: Average SSA,
// then the funnel stages (On Track / Behind / Critical) as counts + share, and
// the tracked core-school total. On Track reads green, Critical red.
export function CceoKpiStrip() {
  const avgSsa   = cceoKpis.find((k) => k.key === "avg_ssa");
  const onTrack  = cceoKpis.find((k) => k.key === "on_track");
  const behind   = cceoKpis.find((k) => k.key === "behind");
  const critical = cceoKpis.find((k) => k.key === "critical");
  const totalCore = cceoKpis.find((k) => k.key === "total_core");
  const totalCoreCount = totalCore ? Number(totalCore.value.replace(/,/g, "")) : 128;

  const metrics: MetricCell[] = [
    {
      key: "avg_ssa",
      label: "Average SSA Score",
      value: avgSsa?.value ?? "7.6",
      unit: avgSsa?.subValue ?? "/10",
      icon: Gauge,
      delta: { dir: "up", text: `+${avgSsa?.trendDelta ?? "0.3"} ${avgSsa?.trendSuffix ?? "vs Apr 2025"}` },
    },
    {
      key: "on_track",
      label: "On Track",
      value: countFor(onTrack, totalCoreCount),
      unit: "schools",
      icon: CheckCircle2,
      tone: "good",
      caption: `${percentFromKpi(onTrack)}% of ${totalCoreCount}`,
    },
    {
      key: "behind",
      label: "Behind",
      value: countFor(behind, totalCoreCount),
      unit: "schools",
      icon: Clock,
      caption: `${percentFromKpi(behind)}%`,
    },
    {
      key: "critical",
      label: "Critical",
      value: countFor(critical, totalCoreCount),
      unit: "schools",
      icon: AlertOctagon,
      tone: "alert",
      caption: `${percentFromKpi(critical)}%`,
    },
    {
      key: "total_core",
      label: "Core Schools",
      value: totalCoreCount,
      unit: "tracked",
      icon: School,
    },
  ];

  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-5" />;
}

// ───────────── Helpers ─────────────

function percentFromKpi(k: typeof cceoKpis[number] | undefined): number {
  if (!k) return 0;
  const sub = k.subValue ?? "";
  const m = sub.match(/(\d+(?:\.\d+)?)%/);
  if (m) return Number(m[1]);
  const t = k.trendDelta.match(/(\d+(?:\.\d+)?)/);
  return t ? Number(t[1]) : 0;
}

function countFor(k: typeof cceoKpis[number] | undefined, total: number): number {
  if (!k) return 0;
  const v = Number(String(k.value).replace(/,/g, ""));
  if (Number.isFinite(v) && v > 0) return v;
  return Math.round((total * percentFromKpi(k)) / 100);
}
