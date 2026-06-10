"use client";

// HR working-queue KPIs as the dense MetricStrip (same format as every other
// dashboard). Each cell deep-links to its queue, so the row reads as "here's
// what's open, here's how to act." Open HR Decisions reads red (alert).
// Lives as a client component so the Lucide icon refs never cross the
// server→client boundary (the HR page is a Server Component).

import { AlertTriangle, ClipboardList, Inbox, Layers } from "lucide-react";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

const HR_KPI_CELLS: MetricCell[] = [
  { key: "reviews",      href: "/team-targets?view=reviews",      label: "Active Performance Reviews", value: "12", caption: "Across 5 program leads",   icon: ClipboardList },
  { key: "support",      href: "/team-targets?view=support",      label: "Staff Flagged for Support",  value: "4",  caption: "Requires HR + PL review",  icon: AlertTriangle },
  { key: "hr-decisions", href: "/team-targets?view=hr-decisions", label: "Open HR Decisions",          value: "3",  caption: "Routed from CD / RVP",     icon: Inbox, tone: "alert" },
  { key: "barriers",     href: "/field-intelligence",             label: "Aggregated Barriers",        value: "18", caption: "Field signals this month", icon: Layers },
];

export function HrKpiStrip() {
  return <MetricStrip metrics={HR_KPI_CELLS} columns="grid-cols-2 sm:grid-cols-4" />;
}
