"use client";

import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  Inbox,
  Send,
  Target,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { acctKpis, type AcctKpi } from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const ICON: Record<AcctKpi["iconKey"], LucideIcon> = {
  available:   Wallet,
  received:    Inbox,
  disbursed:   Send,
  pending:     Clock,
  overdue:     AlertTriangle,
  utilization: Target,
};

const TONE: Record<
  AcctKpi["iconKey"],
  { bg: string; fg: string; spark: string }
> = {
  available:   { bg: "bg-emerald-50",  fg: "text-emerald-600", spark: "#10B981" },
  received:    { bg: "bg-sky-50",      fg: "text-sky-600",     spark: "#3B82F6" },
  disbursed:   { bg: "bg-emerald-50",  fg: "text-emerald-600", spark: "#10B981" },
  pending:     { bg: "bg-amber-50",    fg: "text-amber-600",   spark: "#F59E0B" },
  overdue:     { bg: "bg-rose-50",     fg: "text-rose-600",    spark: "#F43F5E" },
  utilization: { bg: "bg-sky-50",      fg: "text-sky-600",     spark: "#3B82F6" },
};

// KPI strip — six finance tiles that answer "where does the money stand."
//
// Each tile follows the same anatomy:
//   • Top:       UPPERCASE LABEL · soft icon pill
//   • Middle:    hero number (largest type in the dashboard)
//   • Bottom:    delta pill + supporting caption  |  spark or ring
//
// Numbers are tabular + lining so digits sit on a uniform baseline,
// and the hero number carries a soft text-shadow that ties tile to tone.
export function ConsoleKpiStrip() {
  return (
    <section className="px-6 pb-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 lg:gap-3.5">
        {acctKpis.map((k, i) => (
          <Tile key={k.key} k={k} stagger={`stagger-${i + 1}`} />
        ))}
      </div>
    </section>
  );
}

function Tile({ k, stagger }: { k: AcctKpi; stagger: string }) {
  const Icon = ICON[k.iconKey];
  const tone = TONE[k.iconKey];
  const deltaUp = k.delta?.startsWith("+");
  const deltaDown = k.delta?.startsWith("-");
  // "overdue" + "pending" tiles invert polarity: a decrease is good.
  const inverted = k.iconKey === "overdue" || k.iconKey === "pending";
  const deltaPositive = inverted ? deltaDown : deltaUp;

  return (
    <article
      className={cn(
        "card card-lift cursor-default tile-in flex flex-col bg-white relative overflow-hidden",
        "px-4 pt-3.5 pb-3",
        stagger,
      )}
    >
      <div className="flex items-start justify-between gap-2 min-w-0 mb-2">
        <span className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.08em] leading-[1.25] line-clamp-2 flex-1">
          {k.label}
        </span>
        <span
          className={cn(
            "w-7 h-7 rounded-lg grid place-items-center shrink-0",
            tone.bg,
          )}
          aria-hidden
        >
          <Icon size={13} className={tone.fg} strokeWidth={2.2} />
        </span>
      </div>

      <div className="min-w-0">
        <span className="block text-[22px] xl:text-[24px] font-extrabold tabular leading-none text-slate-900 num-hero truncate">
          {k.value}
        </span>
      </div>

      <div className="flex items-center justify-between gap-2 min-w-0 mt-2">
        <div className="min-w-0 flex items-center gap-1.5 flex-wrap">
          {k.delta && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 px-1.5 py-[1.5px] rounded-md text-[9.5px] font-extrabold tabular shrink-0",
                deltaPositive
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-rose-50 text-rose-700",
              )}
            >
              {deltaUp ? <ArrowUpRight size={9} strokeWidth={2.5} /> : <ArrowDownRight size={9} strokeWidth={2.5} />}
              {k.delta}
            </span>
          )}
          <span className="text-caption text-slate-500 font-semibold truncate">
            {k.caption}
          </span>
        </div>
        {typeof k.ringPct === "number" && <Ring pct={k.ringPct} />}
      </div>

      {/* Bottom-spanning sparkline (decorative · sits behind content) */}
      {k.sparkSeed !== undefined && typeof k.ringPct !== "number" && (
        <Spark seed={k.sparkSeed} color={tone.spark} />
      )}
    </article>
  );
}

function Ring({ pct }: { pct: number }) {
  const SIZE = 40;
  const STROKE = 4.5;
  const R = (SIZE - STROKE) / 2;
  const C = 2 * Math.PI * R;
  const dash = C * (1 - pct / 100);
  return (
    <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="-rotate-90"
      >
        <defs>
          <linearGradient id="kpi-ring" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#60A5FA" />
            <stop offset="100%" stopColor="#2563EB" />
          </linearGradient>
        </defs>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} stroke="#EEF2F4" strokeWidth={STROKE} fill="none" />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          stroke="url(#kpi-ring)"
          strokeWidth={STROKE}
          fill="none"
          strokeDasharray={C}
          strokeDashoffset={dash}
          strokeLinecap="round"
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-[9.5px] font-extrabold tabular text-sky-700">
        {pct}%
      </span>
    </div>
  );
}

// Decorative sparkline that spans the bottom edge of the tile.
// Generated with a smoother shape than the original triangle wave —
// a low-frequency sine + slight upward trend reads as "realistic
// telemetry" instead of "designer placeholder."
function Spark({ seed, color }: { seed: number; color: string }) {
  const W = 200;
  const H = 36;
  const N = 24;
  const points = Array.from({ length: N }).map((_, i) => {
    const x = (i / (N - 1)) * W;
    // Two overlapping sine waves create more natural-looking movement.
    const y =
      H -
      6 -
      Math.sin(i * 0.5 + seed * 0.7) * 4 -
      Math.sin(i * 0.18 + seed * 1.2) * 6 -
      (i / N) * 5;
    return { x, y: Math.max(2, Math.min(H - 2, y)) };
  });
  const linePts = points
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");
  const areaPts = `0,${H} ${linePts} ${W},${H}`;
  const gradId = `kpi-spark-${seed}`;
  return (
    <svg
      width="100%"
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="absolute left-0 right-0 bottom-0 pointer-events-none opacity-90"
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPts} fill={`url(#${gradId})`} />
      <polyline
        points={linePts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.85}
      />
    </svg>
  );
}
