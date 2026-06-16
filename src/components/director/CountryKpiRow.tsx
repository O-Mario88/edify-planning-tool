"use client";

import {
  Target,
  Building2,
  ShieldCheck,
  Users,
  Cloud,
  Wallet,
  PieChart,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import { countryKpis, type CountryKpi } from "@/lib/director-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Country Director KPI row — 8 metrics as one dense MetricStrip. Trend deltas
// are preserved (real signal); the sparkline/colored-tile chrome is dropped.

const iconMap: Record<CountryKpi["icon"], LucideIcon> = {
  target:        Target,
  school:        Building2,
  shield:        ShieldCheck,
  users:         Users,
  cloud:         Cloud,
  wallet:        Wallet,
  pieChart:      PieChart,
  alertTriangle: AlertTriangle,
};

export function CountryKpiRow() {
  // Country KPIs are fabricated (28,450 schools / UGX 5.29B) — they contradict
  // the live ~700-school DB. Withhold in production.
  if (!isMockAllowed()) return <InsufficientData surface="country KPIs" />;
  const metrics: MetricCell[] = countryKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    icon: iconMap[k.icon],
    delta: { dir: k.trend.tone === "up" ? "up" : "down", text: `${k.trend.delta}${k.trend.suffix ? ` ${k.trend.suffix}` : ""}` },
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8" />;
}
