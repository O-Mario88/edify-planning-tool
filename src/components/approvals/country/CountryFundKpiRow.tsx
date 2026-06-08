"use client";

import {
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  RotateCcw,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { countryFundKpis, type CountryFundKpi } from "@/lib/country-fund-approvals-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

// Country-Director fund-approval KPIs — one dense MetricStrip (the canonical
// app-wide KPI-row pattern).

const ICON_MAP: Record<CountryFundKpi["icon"], LucideIcon> = {
  wallet:      Wallet,
  clock:       Clock,
  checkCircle: CheckCircle2,
  rotateCcw:   RotateCcw,
  calendar:    Calendar,
  building:    Building2,
};

export function CountryFundKpiRow() {
  const metrics: MetricCell[] = countryFundKpis.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    icon: ICON_MAP[k.icon],
    delta: k.delta
      ? { dir: k.deltaTone === "up" ? "up" : "down", text: `${k.delta}${k.caption ? ` · ${k.caption}` : ""}` }
      : undefined,
    caption: !k.delta ? k.caption : undefined,
  }));
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
    </section>
  );
}
