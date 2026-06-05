"use client";

import {
  User,
  CalendarDays,
  CalendarHeart,
  Lock,
  RotateCw,
  Users,
  type LucideIcon,
} from "lucide-react";
import { leaveKpis, type LeaveKpi } from "@/lib/leave-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// 13 leave metrics as one dense MetricStrip (was a 2/3/6 grid of large cards
// that competed with the hero above). Value + label + the caption context;
// the fabricated trend pills were dropped — the caption carries the real info.

const iconMap: Record<LeaveKpi["icon"], LucideIcon> = {
  user:          User,
  calendarDays:  CalendarDays,
  calendarHeart: CalendarHeart,
  lock:          Lock,
  rotate:        RotateCw,
  users:         Users,
};

export function LeaveKpiRow() {
  const metrics: MetricCell[] = leaveKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    unit: k.unit,
    caption: k.caption,
    icon: iconMap[k.icon],
  }));
  return <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />;
}
