"use client";

// Portfolio-at-a-glance KPI strip for School Directory — the canonical KpiStrip
// with per-cell icons. Server components can't pass Lucide icon refs across the
// boundary, so this thin client wrapper maps each metric key to its icon and
// forwards plain backend-derived values to KpiStrip. Values come from the page's
// live backend fetch (aggregate counts), so the strip is backend-driven and
// filter-aware — never mock.

import { School, Briefcase, ShieldCheck, Network, MapPinOff, CheckCircle2, Clock, type LucideIcon } from "lucide-react";
import { KpiStrip, type KpiStripItem, type KpiTone } from "@/components/ui/kpi-strip";
import type { DirectoryMetric } from "@/lib/school-directory/directory";

const ICONS: Record<string, LucideIcon> = {
  total: School,
  client: Briefcase,
  core: ShieldCheck,
  clustered: Network,
  unclustered: MapPinOff,
  ssa_done: CheckCircle2,
  ssa_miss: Clock,
};

const TONE: Record<string, KpiTone> = { default: "default", alert: "danger", good: "success" };

export function DirectoryKpiStrip({ metrics, title = "Portfolio at a glance" }: { metrics: DirectoryMetric[]; title?: string }) {
  const items: KpiStripItem[] = metrics.map((m) => {
    const Icon = ICONS[m.key];
    return {
      id: m.key,
      label: m.label,
      value: m.value,
      subValue: m.caption,
      icon: Icon ? <Icon size={11} /> : undefined,
      tone: TONE[m.tone ?? "default"] ?? "default",
      subTone: "muted",
    };
  });
  return <KpiStrip title={title} items={items} columns="grid-cols-4 md:grid-cols-8" />;
}
