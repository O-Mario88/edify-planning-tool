"use client";

import {
  Database,
  ShieldCheck,
  Clock,
  AlertOctagon,
  Users,
  type LucideIcon,
} from "lucide-react";
import { impactKpis, type ImpactKpi } from "@/lib/impact-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// Impact-Assessment KPI row — 5 metrics as one dense MetricStrip. Share (% of
// total) carried as the value unit; trend kept; cells deep-link via href.

const ICON: Record<ImpactKpi["icon"], LucideIcon> = {
  database:     Database,
  shieldCheck:  ShieldCheck,
  clock:        Clock,
  alertOctagon: AlertOctagon,
  users:        Users,
};

export function ImpactKpiRow() {
  const metrics: MetricCell[] = impactKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    unit: k.share ? `(${k.share})` : undefined,
    icon: ICON[k.icon],
    href: k.href,
    delta: { dir: k.trend.tone === "up" ? "up" : "down", text: k.trend.label },
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-5" />;
}
