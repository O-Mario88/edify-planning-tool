"use client";

import {
  Cloud,
  RefreshCw,
  School,
  ShieldCheck,
  Target,
  Users,
  type LucideIcon,
} from "lucide-react";
import { cceoOperatingKpis, type CceoOperatingKpi } from "@/lib/cceo-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// CCEO operating KPIs — 6 metrics as one dense MetricStrip. Trend deltas kept;
// the donut rings + colored tiles dropped to keep the band calm.

const ICON_MAP: Record<CceoOperatingKpi["icon"], LucideIcon> = {
  school:      School,
  users:       Users,
  shieldCheck: ShieldCheck,
  target:      Target,
  cloud:       Cloud,
  refresh:     RefreshCw,
};

export function CceoSixKpiRow() {
  const metrics: MetricCell[] = cceoOperatingKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    unit: k.unit,
    icon: ICON_MAP[k.icon],
    delta: { dir: k.deltaTone === "up" ? "up" : "down", text: `${k.delta}${k.caption ? ` · ${k.caption}` : ""}` },
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6" />;
}
