"use client";

import {
  School,
  CheckCircle2,
  Users,
  Star,
  AlertTriangle,
  Building2,
  TrendingUp,
  ArrowDownRight,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import {
  MobileSubpageShell,
  MobileKpiGrid,
  MobileSectionCard,
  type MobileKpiTile,
  type KpiTone,
} from "@/components/mobile/views/MobileSubpageShell";
import {
  ssaKpis,
  ssaUser,
  ssaNotificationCount,
  interventionScores,
  districtSsaPerformance,
  ssaYearlyTrend,
} from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const KPI_ICON: Record<string, LucideIcon> = {
  school:        School,
  checkCircle:   CheckCircle2,
  users:         Users,
  star:          Star,
  alertTriangle: AlertTriangle,
  building:      Building2,
};

const KPI_TONE: Record<string, KpiTone> = {
  edify:   "edify",
  amber:   "amber",
  rose:    "rose",
  emerald: "green",
};

function barColor(score: number) {
  if (score >= 7.0) return "#10b981";
  if (score >= 6.0) return "#f59e0b";
  return "#ef4444";
}

export function SsaMobileView() {
  const tiles: MobileKpiTile[] = ssaKpis.map((k) => ({
    key: k.key,
    Icon: KPI_ICON[k.icon] ?? School,
    label: k.label,
    value: `${k.value}${k.unit ?? ""}`,
    caption: k.caption ?? (k.trend ? `${k.trend.delta}` : undefined),
    tone: KPI_TONE[k.iconTone] ?? "edify",
  }));

  const trendDelta = (
    ssaYearlyTrend[ssaYearlyTrend.length - 1].score -
    ssaYearlyTrend[0].score
  ).toFixed(2);

  return (
    <MobileSubpageShell
      title="SSA Performance"
      subtitle={`Country M&E · ${ssaYearlyTrend.length} years tracked`}
      initials={ssaUser.initials}
      notificationsCount={ssaNotificationCount}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      {/* Yearly trend mini-chart */}
      <MobileSectionCard
        title="SSA Performance Trend by Year"
        subtitle={`Annual average · ${trendDelta} pts since ${ssaYearlyTrend[0].year}`}
      >
        <div className="px-3 pb-3">
          <ul className="space-y-1.5">
            {ssaYearlyTrend.map((y) => {
              const widthPct = (y.score / 10) * 100;
              return (
                <li key={y.year} className="flex items-center gap-2 text-[11px]">
                  <span className="w-10 muted font-semibold tabular shrink-0">{y.year}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${widthPct}%`, backgroundColor: barColor(y.score) }}
                    />
                  </div>
                  <span className="w-10 text-right font-extrabold tabular shrink-0">
                    {y.score.toFixed(2)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </MobileSectionCard>

      {/* Intervention scores */}
      <MobileSectionCard title="Intervention Performance" subtitle="Average score across the 8 SSA areas">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {interventionScores.map((row) => (
            <li key={row.label} className="px-3 py-2 flex items-center gap-2">
              <span className="text-caption muted font-bold tabular shrink-0 w-5">#{row.rank}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[11.5px] font-semibold leading-tight truncate">{row.label}</div>
                <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${(row.score / 10) * 100}%`, backgroundColor: barColor(row.score) }}
                  />
                </div>
              </div>
              <span className="text-[11.5px] font-extrabold tabular shrink-0 w-10 text-right">
                {row.score.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      </MobileSectionCard>

      {/* District performance list */}
      <MobileSectionCard
        title="Districts"
        subtitle="Ranked by average SSA"
        ctaLabel="View All"
        ctaHref="#districts"
      >
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {districtSsaPerformance.map((d) => (
            <li key={d.district} className="px-3 py-2.5 flex items-center gap-3">
              <span className="text-caption muted font-bold tabular shrink-0 w-6">#{d.rank}</span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight">{d.district}</div>
                <div className="text-caption muted truncate">
                  {d.schoolsAssessed} schools · {d.completionRate}% complete
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-body-lg font-extrabold tabular leading-none">
                  {d.averageScore.toFixed(2)}
                </div>
                <div className={cn(
                  "text-[10px] font-semibold mt-0.5 inline-flex items-center gap-0.5",
                  d.trend === "up" ? "text-emerald-600" : "text-rose-600",
                )}>
                  {d.trend === "up" ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                  {d.highRiskSchools} high-risk
                </div>
              </div>
            </li>
          ))}
        </ul>
      </MobileSectionCard>

      <div className="muted text-caption inline-flex items-center gap-1 px-1">
        <TrendingUp size={11} />
        Annual rollup so leaders can see multi-year school progress at a glance.
      </div>
    </MobileSubpageShell>
  );
}
