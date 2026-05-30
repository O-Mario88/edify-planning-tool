"use client";

import { motion, useReducedMotion } from "motion/react";
import {
  Target,
  Users,
  ClipboardList,
  CalendarCheck,
  ShieldCheck,
  Layers,
  Wallet,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { teamKpis, type TeamKpi } from "@/lib/cpl-mock";
import { aggregateTeam, ccoOnTrackRatio } from "@/lib/cpl-engine";
import { MiniSparkline } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { fadeUp, spring, stagger, staggerContainer } from "@/lib/motion";

const iconMap: Record<TeamKpi["icon"], LucideIcon> = {
  target:        Target,
  users:         Users,
  clipboardList: ClipboardList,
  calendarCheck: CalendarCheck,
  shieldCheck:   ShieldCheck,
  layers:        Layers,
  wallet:        Wallet,
  alertTriangle: AlertTriangle,
};

const tileClass: Record<TeamKpi["iconTone"], string> = {
  edify:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  green:  "bg-green-100 text-[#166534]",
  amber:  "bg-amber-100 text-amber-800",
  red:    "bg-red-100 text-red-700",
  blue:   "bg-blue-100 text-[#1e40af]",
  violet: "bg-violet-100 text-violet-700",
};

const sparkColor: Record<TeamKpi["iconTone"], string> = {
  edify:  "#527083",
  green:  "#16a34a",
  amber:  "#f59e0b",
  red:    "#ef4444",
  blue:   "#2563eb",
  violet: "#7c3aed",
};

export function TeamKpiRow() {
  // Overlay derived values onto the visible KPI tiles so the row is no
  // longer a frozen seed. Right now: "CCEOs On Track" and "Team Backlog"
  // both derive from the engine. The rest still read from the seed
  // until their underlying collections exist.
  const team = aggregateTeam();
  const onTrack = ccoOnTrackRatio();
  const tiles: TeamKpi[] = teamKpis.map((k) => {
    if (k.key === "cceos_track") {
      return {
        ...k,
        value: `${onTrack.pct}%`,
        trend: { ...k.trend, suffix: `${onTrack.onTrack} of ${onTrack.total} CCEOs` },
      };
    }
    if (k.key === "team_backlog") {
      return {
        ...k,
        value: String(team.backlogTotal),
        trend: { ...k.trend, delta: `${team.salesforcePendingTotal} SF pending` },
      };
    }
    return k;
  });
  return (
    <motion.section
      className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8 gap-2 md:gap-3"
      variants={staggerContainer(0.04, stagger.tile)}
      initial="hidden"
      animate="visible"
    >
      {tiles.map((k) => (
        <KpiTile key={k.key} kpi={k} />
      ))}
    </motion.section>
  );
}

function KpiTile({ kpi }: { kpi: TeamKpi }) {
  const Icon = iconMap[kpi.icon];
  const reduce = useReducedMotion();
  const trendCls =
    kpi.trend.tone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
  return (
    <motion.div
      variants={fadeUp}
      transition={reduce ? { duration: 0 } : spring.soft}
      whileHover={reduce ? undefined : { y: -2, transition: spring.hover }}
      className="card-elevated card-lift p-2 lg:p-2.5 overflow-hidden cursor-default"
    >
      <div className="flex items-start gap-1.5">
        <span
          className={cn(
            "w-6 h-6 rounded-full flex items-center justify-center shrink-0",
            tileClass[kpi.iconTone],
          )}
        >
          <Icon size={12} />
        </span>
        <div className="min-w-0 flex-1 text-[10px] muted font-bold leading-tight line-clamp-1 uppercase tracking-wide">
          {kpi.label}
        </div>
      </div>
      <div className="text-[17px] font-extrabold tabular mt-1.5 leading-none truncate num-hero text-[var(--text-primary)]" style={{ letterSpacing: "-0.02em" }}>{kpi.value}</div>
      {kpi.humanLabel ? (
        <div className="text-[11px] font-semibold text-[var(--color-edify-text)] leading-snug mt-1 line-clamp-2">
          {kpi.humanLabel}
        </div>
      ) : null}
      <div className={cn("text-[9.5px] font-semibold mt-1 flex items-center gap-0.5 truncate", trendCls)}>
        {kpi.trend.tone === "up" ? <ArrowUpRight size={9} className="shrink-0" /> : <ArrowDownRight size={9} className="shrink-0" />}
        <span className="truncate">
          {kpi.trend.delta}
          {kpi.trend.suffix ? <span className="muted font-medium ml-1">{kpi.trend.suffix}</span> : null}
        </span>
      </div>
      <div className="mt-1 -mx-1 overflow-hidden">
        <MiniSparkline
          seed={kpi.spark.seed}
          trend={kpi.spark.trend}
          color={sparkColor[kpi.iconTone]}
          height={22}
        />
      </div>
    </motion.div>
  );
}
