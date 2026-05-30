"use client";

import { motion } from "motion/react";
import {
  Briefcase,
  PlayCircle,
  Building2,
  Handshake,
  Users,
  Wallet,
  CalendarDays,
  ShieldCheck,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { MiniSparkline } from "@/components/ui/primitives";
import { type SpecialProjectKpi } from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<SpecialProjectKpi["icon"], LucideIcon> = {
  briefcase: Briefcase,
  play:      PlayCircle,
  school:    Building2,
  handshake: Handshake,
  users:     Users,
  wallet:    Wallet,
  calendar:  CalendarDays,
  shield:    ShieldCheck,
};

const tile: Record<SpecialProjectKpi["iconTone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  green:   "bg-green-100 text-[#166534]",
  blue:    "bg-blue-100 text-[#1e40af]",
  amber:   "bg-amber-100 text-amber-800",
  violet:  "bg-violet-100 text-violet-700",
  rose:    "bg-rose-100 text-rose-700",
  emerald: "bg-[#d1fae5] text-[#065f46]",
  orange:  "bg-orange-100 text-[#9a3412]",
};

const sparkColor: Record<SpecialProjectKpi["iconTone"], string> = {
  edify:   "#527083",
  green:   "#16a34a",
  blue:    "#2563eb",
  amber:   "#f59e0b",
  violet:  "#7c3aed",
  rose:    "#e11d48",
  emerald: "#10b981",
  orange:  "#ea580c",
};

export function SpKpiRow({ kpis }: { kpis: SpecialProjectKpi[] }) {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3">
      {kpis.map((k, i) => (
        <Tile key={k.key} kpi={k} idx={i} />
      ))}
    </section>
  );
}

function Tile({ kpi, idx }: { kpi: SpecialProjectKpi; idx: number }) {
  const Icon = iconMap[kpi.icon];
  const trendCls =
    kpi.trend.tone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: idx * 0.03 }}
      className="card p-3 overflow-hidden"
    >
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center shrink-0",
            tile[kpi.iconTone],
          )}
        >
          <Icon size={14} />
        </span>
        <div className="min-w-0 flex-1 text-caption muted font-semibold leading-tight line-clamp-2">
          {kpi.label}
        </div>
      </div>
      <div className="text-[20px] font-extrabold tabular mt-2 leading-none truncate">{kpi.value}</div>
      <div className={cn("text-caption font-semibold mt-1 flex items-center gap-1 truncate", trendCls)}>
        {kpi.trend.tone === "up" ? <ArrowUpRight size={10} className="shrink-0" /> : <ArrowDownRight size={10} className="shrink-0" />}
        <span className="truncate">
          {kpi.trend.delta}
          <span className="muted font-medium ml-1">vs Apr</span>
        </span>
      </div>
      <div className="mt-1 -mx-1 overflow-hidden">
        <MiniSparkline
          seed={kpi.spark.seed}
          trend={kpi.spark.trend}
          color={sparkColor[kpi.iconTone]}
          height={20}
        />
      </div>
    </motion.div>
  );
}
