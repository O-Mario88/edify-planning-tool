"use client";

import { motion } from "motion/react";
import {
  Building2,
  Users,
  Briefcase,
  Shield,
  Building,
  UserPlus,
  Handshake,
  CheckCircle2,
  XCircle,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { MiniSparkline } from "@/components/ui/primitives";
import { type SchoolKpi } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<SchoolKpi["icon"], LucideIcon> = {
  school:      Building2,
  users:       Users,
  briefcase:   Briefcase,
  shield:      Shield,
  schoolOff:   Building,
  userPlus:    UserPlus,
  handshake:   Handshake,
  checkCircle: CheckCircle2,
  xCircle:     XCircle,
};

const tile: Record<SchoolKpi["iconTone"], string> = {
  edify:   "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  green:   "bg-green-100 text-[#166534]",
  blue:    "bg-blue-100 text-[#1e40af]",
  violet:  "bg-violet-100 text-violet-700",
  rose:    "bg-rose-100 text-rose-700",
  amber:   "bg-amber-100 text-amber-800",
  emerald: "bg-[#d1fae5] text-[#065f46]",
  red:     "bg-red-100 text-red-700",
};

const sparkColor: Record<SchoolKpi["iconTone"], string> = {
  edify:   "#527083",
  green:   "#16a34a",
  blue:    "#2563eb",
  violet:  "#7c3aed",
  rose:    "#e11d48",
  amber:   "#f59e0b",
  emerald: "#10b981",
  red:     "#ef4444",
};

export function SchoolKpiRow({ kpis }: { kpis: SchoolKpi[] }) {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3">
      {kpis.map((k, i) => (
        <KpiTile key={k.key} kpi={k} idx={i} />
      ))}
    </section>
  );
}

function KpiTile({ kpi, idx }: { kpi: SchoolKpi; idx: number }) {
  const Icon = iconMap[kpi.icon];
  const trendCls =
    kpi.delta.tone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: idx * 0.03 }}
      className="card card-lift cursor-default p-3 overflow-hidden"
    >
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "w-9 h-9 rounded-full flex items-center justify-center shrink-0",
            tile[kpi.iconTone],
          )}
        >
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1 text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2">
          {kpi.label}
        </div>
      </div>
      <div className={cn(
        "text-[18px] font-extrabold tabular mt-2.5 leading-none truncate num-hero text-[var(--text-primary)]",
        kpi.delta.tone === "up" ? "glow-emerald" : "glow-rose",
      )}>
        {kpi.value.toLocaleString()}
      </div>
      <div className={cn("text-[10px] font-semibold mt-1 flex items-center gap-1 truncate", trendCls)}>
        {kpi.delta.tone === "up" ? <ArrowUpRight size={9} className="shrink-0" /> : <ArrowDownRight size={9} className="shrink-0" />}
        <span className="truncate">
          {kpi.delta.pct}
          <span className="muted font-medium ml-1">vs Apr</span>
        </span>
      </div>
      <div className="mt-1 -mx-0.5 overflow-hidden">
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
