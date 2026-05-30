import {
  Target,
  Building2,
  ShieldCheck,
  Users,
  Cloud,
  Wallet,
  PieChart,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { countryKpis, type CountryKpi } from "@/lib/director-mock";
import { Tile, type TileTone } from "@/components/ui/Tile";
import { cn } from "@/lib/utils";

// Country Director KPI row — 8 tiles. Built on the shared `Tile`
// primitive so the visual treatment exactly matches the /approvals
// page (the design source of truth).

const iconMap: Record<CountryKpi["icon"], LucideIcon> = {
  target:        Target,
  school:        Building2,
  shield:        ShieldCheck,
  users:         Users,
  cloud:         Cloud,
  wallet:        Wallet,
  pieChart:      PieChart,
  alertTriangle: AlertTriangle,
};

const TONE: Record<CountryKpi["iconTone"], TileTone> = {
  edify:  "edify",
  green:  "emerald",
  amber:  "amber",
  red:    "rose",
  blue:   "sky",
  violet: "violet",
};

export function CountryKpiRow() {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-8 gap-2 sm:gap-3">
      {countryKpis.map((k, i) => (
        <KpiTile key={k.key} kpi={k} index={i} />
      ))}
    </section>
  );
}

function KpiTile({ kpi, index }: { kpi: CountryKpi; index: number }) {
  const Icon = iconMap[kpi.icon];
  const up = kpi.trend.tone === "up";
  const Arrow = up ? ArrowUpRight : ArrowDownRight;
  const trendColor = up
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-rose-600 dark:text-rose-400";

  return (
    <Tile
      index={index}
      tone={TONE[kpi.iconTone]}
      icon={<Icon size={15} />}
      label={kpi.label}
      value={kpi.value}
      trend={
        <span className={cn("inline-flex items-center gap-0.5 truncate", trendColor)}>
          <Arrow size={11} className="shrink-0" />
          <span className="truncate">
            {kpi.trend.delta}
            {kpi.trend.suffix ? (
              <span className="muted font-medium ml-1">{kpi.trend.suffix}</span>
            ) : null}
          </span>
        </span>
      }
    />
  );
}
