"use client";

import {
  School as SchoolIcon,
  CheckCircle2,
  TrendingUp,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { ProgressRing } from "@/components/ui/primitives";
import { cceoKpis, type CceoKpi } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const STATIC_ICON: Record<"school" | "checkCircle" | "trendingUp", LucideIcon> = {
  school:      SchoolIcon,
  checkCircle: CheckCircle2,
  trendingUp:  TrendingUp,
};

const ICON_TONE: Record<string, string> = {
  school:       "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  checkCircle:  "bg-emerald-100 text-emerald-700",
  trendingUp:   "bg-violet-100  text-violet-700",
};

const RING_COLOR: Record<"edify" | "green" | "amber" | "rose", string> = {
  edify: "var(--color-edify-primary)",
  green: "#10b981",
  amber: "#f59e0b",
  rose:  "#ef4444",
};

export function CceoKpiRow() {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {cceoKpis.map((k) => (
        <KpiCard key={k.key} k={k} />
      ))}
    </section>
  );
}

function KpiCard({ k }: { k: CceoKpi }) {
  const trendCls = k.trendTone === "up" ? "text-emerald-600" : "text-rose-600";
  const TrendIcon = k.trendTone === "up" ? ArrowUpRight : ArrowDownRight;
  return (
    <div className="card p-3 lg:p-3.5 rounded-2xl flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[11.5px] muted font-semibold leading-tight line-clamp-2 min-h-[28px]">
          {k.label}
        </div>
        {k.visual.kind === "icon" ? (
          <span
            className={cn(
              "h-9 w-9 rounded-xl grid place-items-center shrink-0",
              ICON_TONE[k.visual.icon],
            )}
          >
            {(() => {
              const Icon = STATIC_ICON[k.visual.icon];
              return <Icon size={16} />;
            })()}
          </span>
        ) : (
          <div className="shrink-0">
            <ProgressRing
              pct={k.visual.pct}
              size={40}
              stroke={5}
              color={RING_COLOR[k.visual.color]}
            />
          </div>
        )}
      </div>

      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-[26px] lg:text-[28px] font-extrabold tabular leading-none">
          {k.value}
        </span>
        {k.subValue && (
          <span className="text-[12px] muted font-semibold tabular leading-none">
            {k.subValue}
          </span>
        )}
      </div>

      <div className={cn("mt-1.5 inline-flex items-center gap-1 text-caption font-semibold", trendCls)}>
        <TrendIcon size={11} />
        {k.trendDelta}
        <span className="muted font-medium">{k.trendSuffix}</span>
      </div>
    </div>
  );
}
