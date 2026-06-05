"use client";

import {
  Target,
  Users,
  ClipboardList,
  CalendarCheck,
  ShieldCheck,
  Layers,
  Wallet,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import { teamKpis, type TeamKpi } from "@/lib/cpl-mock";
import { aggregateTeam, ccoOnTrackRatio } from "@/lib/cpl-engine";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// CPL team KPI row — 8 metrics as one dense MetricStrip. Two values are
// engine-derived (CCEOs On Track, Team Backlog); trend deltas are preserved.

const iconMap: Record<TeamKpi["icon"], LucideIcon> = {
  target:        Target,
  users:         Users,
  clipboardList: ClipboardList,
  calendarCheck: CalendarCheck,
  shieldCheck:   ShieldCheck,
  layers:        Layers,
  wallet:        Wallet,
  alertTriangle: AlertTriangle,
};

export function TeamKpiRow() {
  // Overlay engine-derived values onto the seed so the row isn't frozen.
  const team = aggregateTeam();
  const onTrack = ccoOnTrackRatio();
  const tiles: TeamKpi[] = teamKpis.map((k) => {
    if (k.key === "cceos_track") {
      return { ...k, value: `${onTrack.pct}%`, trend: { ...k.trend, suffix: `${onTrack.onTrack} of ${onTrack.total} CCEOs` } };
    }
    if (k.key === "team_backlog") {
      return { ...k, value: String(team.backlogTotal), trend: { ...k.trend, delta: `${team.salesforcePendingTotal} SF pending` } };
    }
    return k;
  });
  const metrics: MetricCell[] = tiles.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    icon: iconMap[k.icon],
    delta: { dir: k.trend.tone === "up" ? "up" : "down", text: `${k.trend.delta}${k.trend.suffix ? ` ${k.trend.suffix}` : ""}` },
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8" />;
}
