"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  Cloud,
  RefreshCw,
  School,
  ShieldCheck,
  Target,
  Users,
  type LucideIcon,
} from "lucide-react";
import { cceoOperatingKpis, type CceoOperatingKpi } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<CceoOperatingKpi["icon"], LucideIcon> = {
  school:      School,
  users:       Users,
  shieldCheck: ShieldCheck,
  target:      Target,
  cloud:       Cloud,
  refresh:     RefreshCw,
};

// Each tone is a coordinated trio: icon tile bg / icon color / ring
// stroke. The ring colour follows the tile's accent so the eye reads
// the progress with the icon, not as a separate element.
const ICON_TONE: Record<
  CceoOperatingKpi["iconTone"],
  { iconBg: string; iconColor: string }
> = {
  edify:   { iconBg: "bg-[var(--color-edify-soft)]", iconColor: "text-[var(--color-edify-primary)]" },
  emerald: { iconBg: "bg-emerald-100",               iconColor: "text-emerald-700"                  },
  violet:  { iconBg: "bg-violet-100",                iconColor: "text-violet-700"                   },
  amber:   { iconBg: "bg-amber-100",                 iconColor: "text-amber-700"                    },
  rose:    { iconBg: "bg-rose-100",                  iconColor: "text-rose-700"                     },
  blue:    { iconBg: "bg-sky-100",                   iconColor: "text-sky-700"                      },
};

const RING_STROKE: Record<NonNullable<CceoOperatingKpi["ringTone"]>, string> = {
  emerald: "#10b981",
  amber:   "#f59e0b",
  rose:    "#ef4444",
};

export function CceoSixKpiRow() {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2.5 lg:gap-3">
      {cceoOperatingKpis.map((k, i) => (
        <KpiTile key={k.key} k={k} idx={i} />
      ))}
    </section>
  );
}

function KpiTile({ k, idx }: { k: CceoOperatingKpi; idx: number }) {
  const Icon = ICON_MAP[k.icon];
  const tone = ICON_TONE[k.iconTone];
  const up = k.deltaTone === "up";
  const DeltaIcon = up ? ArrowUpRight : ArrowDownRight;
  const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][idx] ?? "";

  return (
    <div className={cn(
      "card card-lift cursor-default tile-in rounded-2xl p-3 lg:p-3.5 flex flex-col gap-2 overflow-hidden",
      staggerCls,
    )}>
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "w-9 h-9 rounded-xl grid place-items-center shrink-0",
            tone.iconBg,
          )}
        >
          <Icon size={15} className={tone.iconColor} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-caption muted font-semibold leading-tight line-clamp-2 min-h-[26px]">
            {k.label}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="flex items-baseline gap-1 min-w-0">
          <span className={cn(
            "text-[18px] lg:text-[20px] font-extrabold tabular leading-none text-[var(--text-primary)] num-hero",
            up ? "glow-emerald" : "glow-rose",
          )}>
            {k.value}
          </span>
          {k.unit && (
            <span className="text-[13px] muted font-semibold leading-none">{k.unit}</span>
          )}
        </div>

        {/* Donut ring — only renders for KPIs that opted in. */}
        {typeof k.ringPct === "number" && k.ringTone && (
          <ProgressRing pct={k.ringPct} stroke={RING_STROKE[k.ringTone]} />
        )}
      </div>

      <div className="flex items-center gap-1.5 min-w-0">
        <span
          className={cn(
            "inline-flex items-center gap-0.5 text-caption font-bold tabular shrink-0",
            up ? "text-emerald-700" : "text-rose-700",
          )}
        >
          <DeltaIcon size={11} />
          {k.delta}
        </span>
        <span className="text-[10px] muted font-semibold truncate">{k.caption}</span>
      </div>
    </div>
  );
}

// ───────────── ProgressRing ─────────────
//
// Small inline donut chart. SVG-only (no Recharts) so the ring renders
// crisply at the 36px diameter the tile expects.
function ProgressRing({ pct, stroke }: { pct: number; stroke: string }) {
  const SIZE = 38;
  const STROKE = 4;
  const R = (SIZE - STROKE) / 2;
  const C = 2 * Math.PI * R;
  const dashOffset = C * (1 - Math.max(0, Math.min(100, pct)) / 100);

  return (
    <svg
      width={SIZE}
      height={SIZE}
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="shrink-0 -rotate-90"
      role="img"
      aria-label={`${pct}%`}
    >
      <circle
        cx={SIZE / 2}
        cy={SIZE / 2}
        r={R}
        stroke="#eef2f4"
        strokeWidth={STROKE}
        fill="none"
      />
      <circle
        cx={SIZE / 2}
        cy={SIZE / 2}
        r={R}
        stroke={stroke}
        strokeWidth={STROKE}
        fill="none"
        strokeDasharray={C}
        strokeDashoffset={dashOffset}
        strokeLinecap="round"
      />
    </svg>
  );
}
