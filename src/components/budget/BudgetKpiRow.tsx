// Budget KPI row — now the dense MetricStrip, same as every other dashboard.
// The public `items` API (incl. the legacy `hero`/`tone` flags) is preserved so
// all budget dashboards keep calling it unchanged; hierarchy flags are simply
// ignored — the strip renders one uniform, scannable band.

import { type LucideIcon } from "lucide-react";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

export type BudgetKpi = {
  key: string;
  label: string;
  value: string;
  caption?: string;
  delta?: string;
  deltaTone?: "up" | "down";
  Icon: LucideIcon;
  tone?: string; // legacy icon-chip classes — ignored by the strip
  hero?: boolean; // legacy hierarchy flag — ignored by the strip
};

export function BudgetKpiRow({ items }: { items: BudgetKpi[] }) {
  const metrics: MetricCell[] = items.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    caption: k.caption,
    icon: k.Icon,
    delta: k.delta ? { dir: k.deltaTone === "down" ? "down" : "up", text: k.delta } : undefined,
  }));
  return <MetricStrip metrics={metrics} />;
}
