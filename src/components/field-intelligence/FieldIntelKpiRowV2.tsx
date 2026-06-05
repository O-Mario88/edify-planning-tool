"use client";

import {
  Calendar,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  Target,
  TrendingUp,
} from "lucide-react";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// Daily Field Debrief — 6 metrics as one dense MetricStrip.

export function FieldIntelKpiRowV2({
  planned,
  completed,
  verified,
  incomplete,
  rawAchievementPct,
  contextAdjustedPct,
}: {
  planned: number;
  completed: number;
  verified: number;
  incomplete: number;
  rawAchievementPct: number;
  contextAdjustedPct: number;
}) {
  const up = (text: string): MetricCell["delta"] => ({ dir: "up", text: `${text} vs last month` });
  const metrics: MetricCell[] = [
    { key: "planned",    label: "Planned",          value: planned,                    icon: Calendar,    delta: up("↑25%") },
    { key: "completed",  label: "Completed",        value: completed,                  icon: CheckCircle2, delta: up("↑20%") },
    { key: "verified",   label: "Verified",         value: verified,                   icon: ShieldCheck, delta: up("↑50%") },
    { key: "incomplete", label: "Incomplete",       value: incomplete,                 icon: XCircle,     delta: up("↑100%") },
    { key: "raw",        label: "Raw Achievement",  value: `${rawAchievementPct}%`,    icon: Target,      delta: up("↑10pp") },
    { key: "ctx",        label: "Context-Adjusted", value: `${contextAdjustedPct}%`,   icon: TrendingUp,  delta: up("↑8pp") },
  ];
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />;
}
