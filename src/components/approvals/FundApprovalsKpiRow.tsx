"use client";

import {
  Building2,
  CheckCircle2,
  Clock,
  Folder,
  RotateCcw,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { fundApprovalKpis, type FundApprovalKpi } from "@/lib/fund-approvals-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Program-Lead fund-approval KPIs — 6 metrics as one dense MetricStrip.

const ICON_MAP: Record<FundApprovalKpi["icon"], LucideIcon> = {
  wallet:      Wallet,
  clock:       Clock,
  checkCircle: CheckCircle2,
  rotateCcw:   RotateCcw,
  folder:      Folder,
  building:    Building2,
};

export function FundApprovalsKpiRow() {
  // KPI figures (214.6M/128.4M) are fabricated; the live approval queue on the
  // page is the real surface. Withhold the mock money KPIs in production.
  if (!isMockAllowed()) return <InsufficientData surface="fund-approval KPIs" />;
  const metrics: MetricCell[] = fundApprovalKpis.map((k) => ({
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
