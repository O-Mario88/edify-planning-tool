"use client";

import {
  AlertTriangle, Clock, Inbox, Send, Target, Wallet, type LucideIcon,
} from "lucide-react";
import { acctKpis, type AcctKpi } from "@/lib/accountant-console-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const ICON: Record<AcctKpi["iconKey"], LucideIcon> = {
  available: Wallet, received: Inbox, disbursed: Send,
  pending: Clock, overdue: AlertTriangle, utilization: Target,
};

// Value tone by metric: attention metrics tint red, healthy ones green.
const TONE: Record<AcctKpi["iconKey"], MetricCell["tone"]> = {
  available: "good", disbursed: "good", received: "default",
  pending: "alert", overdue: "alert", utilization: "default",
};

// Six finance KPIs — "where the money stands" — as one dense MetricStrip
// (the canonical app-wide KPI-row pattern; rings/sparklines dropped).
export function ConsoleKpiStrip() {
  // Finance KPIs are fabricated (UGX 214.8M / 67% util, "May 2025"); never show
  // fake money figures on the accountant's console in production.
  if (!isMockAllowed()) return <InsufficientData surface="finance KPIs" />;
  const metrics: MetricCell[] = acctKpis.map((k) => {
    const deltaUp = k.delta?.startsWith("+");
    const deltaDown = k.delta?.startsWith("-");
    const inverted = k.iconKey === "overdue" || k.iconKey === "pending";
    const positive = inverted ? deltaDown : deltaUp;
    return {
      key: k.key,
      label: k.label,
      value: k.value,
      icon: ICON[k.iconKey],
      tone: TONE[k.iconKey],
      delta: k.delta
        ? { dir: positive ? "up" : "down", text: `${k.delta}${k.caption ? ` · ${k.caption}` : ""}` }
        : undefined,
      caption: !k.delta ? k.caption : undefined,
    };
  });
  return (
    <section className="px-6 pb-5">
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
    </section>
  );
}
