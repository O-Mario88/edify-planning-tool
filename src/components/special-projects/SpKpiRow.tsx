"use client";

import {
  Briefcase,
  PlayCircle,
  Building2,
  Handshake,
  Users,
  Wallet,
  CalendarDays,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { type SpecialProjectKpi } from "@/lib/special-projects-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// Special-projects KPI row — dense MetricStrip. Trend deltas kept; sparkline
// + colored tiles dropped.
//
// NOTE: this mock-typed variant is retained ONLY for the project-coordinator
// dashboard (out of scope here). The /special-projects page uses the live
// strip inside SpecialProjectsLiveOverview, computed from the backend Project
// list, with no fabricated aggregates.

const iconMap: Record<SpecialProjectKpi["icon"], LucideIcon> = {
  briefcase: Briefcase,
  play:      PlayCircle,
  school:    Building2,
  handshake: Handshake,
  users:     Users,
  wallet:    Wallet,
  calendar:  CalendarDays,
  shield:    ShieldCheck,
};

export function SpKpiRow({ kpis }: { kpis: SpecialProjectKpi[] }) {
  const metrics: MetricCell[] = kpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    icon: iconMap[k.icon],
    delta: { dir: k.trend.tone === "up" ? "up" : "down", text: `${k.trend.delta} vs Apr` },
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-4 xl:grid-cols-5" />;
}
