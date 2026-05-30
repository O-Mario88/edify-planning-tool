import {
  Database,
  ShieldCheck,
  Clock,
  AlertOctagon,
  Users,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { impactKpis, type ImpactKpi } from "@/lib/impact-mock";
import { Tile, type TileTone } from "@/components/ui/Tile";
import { cn } from "@/lib/utils";

// Impact-Assessment KPI row.  Re-built on top of the shared `Tile`
// primitive so every dashboard's KPI strip reads identically to the
// /approvals page (the design source of truth).

const ICON: Record<ImpactKpi["icon"], LucideIcon> = {
  database:     Database,
  shieldCheck:  ShieldCheck,
  clock:        Clock,
  alertOctagon: AlertOctagon,
  users:        Users,
};

const TONE: Record<ImpactKpi["iconTone"], TileTone> = {
  violet: "violet",
  green:  "emerald",
  amber:  "amber",
  rose:   "rose",
  blue:   "sky",
};

export function ImpactKpiRow() {
  // Grid: 5 KPIs across three breakpoints with ZERO dead cells.
  //   • mobile  (2 cols): hero spans 2  +  4 sub-KPIs in 2×2  →  2+2+2
  //   • tablet  (4 cols): hero spans 4  +  4 sub-KPIs in 1×4  →  4+4
  //   • desktop (5 cols): every tile spans 1                   →  5
  // Total Records earns the hero slot because it's the denominator —
  // every other KPI (Verified / Pending / Failed / Partners Active) is
  // a subset of it.
  return (
    <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
      {impactKpis.map((k, i) => (
        <KpiTile
          key={k.key}
          kpi={k}
          index={i}
          className={k.key === "total-records" ? "col-span-2 md:col-span-4 lg:col-span-1" : ""}
        />
      ))}
    </section>
  );
}

function KpiTile({ kpi, index, className }: { kpi: ImpactKpi; index: number; className?: string }) {
  const Icon  = ICON[kpi.icon];
  const Arrow = kpi.trend.tone === "up" ? ArrowUpRight : ArrowDownRight;
  const trendColor =
    kpi.trend.tone === "up"
      ? "text-emerald-700 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";

  return (
    <Tile
      href={kpi.href}
      index={index}
      tone={TONE[kpi.iconTone]}
      icon={<Icon size={15} />}
      className={className}
      label={kpi.label}
      value={
        <span className="flex items-baseline gap-1.5">
          {kpi.value}
          {kpi.share && (
            <span className="text-[12px] font-bold text-[var(--text-muted)] tabular">
              ({kpi.share})
            </span>
          )}
        </span>
      }
      trend={
        <span className={cn("inline-flex items-center gap-0.5", trendColor)}>
          <Arrow size={11} />
          {kpi.trend.label}
        </span>
      }
    />
  );
}
