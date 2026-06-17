"use client";

// MetricStrip — now a thin ADAPTER over the canonical KpiStrip.
//
// KpiStrip is the single system-wide KPI surface (src/components/ui/kpi-strip).
// MetricStrip is retained so the ~30 existing call sites keep working unchanged,
// but they all now render through KpiStrip — one premium design, no divergent
// strip styles. New code should import KpiStrip directly.

import { type LucideIcon } from "lucide-react";
import { KpiStrip, type KpiStripItem, type KpiTone } from "./kpi-strip";

export type MetricDelta = { dir: "up" | "down" | "flat"; text: string };

export type MetricCell = {
  key: string;
  label: string;
  value: string | number;
  unit?: string;
  caption?: string;
  delta?: MetricDelta;
  tone?: "default" | "alert" | "good";
  icon?: LucideIcon;
  href?: string;
  onClick?: () => void;
  active?: boolean;
};

const TONE_MAP: Record<NonNullable<MetricCell["tone"]>, KpiTone> = {
  default: "default",
  alert: "danger",
  good: "success",
};
const DELTA_ARROW = { up: "↑", down: "↓", flat: "–" } as const;
const DELTA_TONE: Record<MetricDelta["dir"], KpiTone> = { up: "success", down: "danger", flat: "muted" };

// Pure mapping (no JSX) — the value/tone/sub-value translation from the legacy
// MetricCell to a KpiStripItem. Exported so it can be unit-tested without
// rendering (the repo's test harness is pure-logic, not component-render).
export function metricToKpiFields(m: MetricCell): Pick<KpiStripItem, "id" | "label" | "value" | "tone" | "subValue" | "subTone" | "href" | "active"> {
  const value = m.unit ? `${typeof m.value === "number" ? m.value.toLocaleString() : m.value}${m.unit === "%" ? "" : " "}${m.unit}` : m.value;
  return {
    id: m.key,
    label: m.label,
    value,
    tone: TONE_MAP[m.tone ?? "default"],
    subValue: m.delta ? `${DELTA_ARROW[m.delta.dir]} ${m.delta.text}` : m.caption,
    subTone: m.delta ? DELTA_TONE[m.delta.dir] : "muted",
    href: m.href,
    active: m.active,
  };
}

function toItem(m: MetricCell): KpiStripItem {
  const Icon = m.icon;
  return { ...metricToKpiFields(m), icon: Icon ? <Icon size={10} /> : undefined, onClick: m.onClick };
}

export function MetricStrip({
  metrics,
  title,
  className,
  columns,
  bare = false,
}: {
  metrics: MetricCell[];
  title?: string;
  className?: string;
  columns?: string;
  bare?: boolean;
}) {
  return <KpiStrip title={title} items={metrics.map(toItem)} columns={columns} bare={bare} className={className} />;
}
