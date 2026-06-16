import { TrendingUp, TrendingDown, Minus, Lightbulb } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  districtSsaComparison,
  clusterSsaComparison,
  interventionSsaComparison,
  generateSsaImprovementInsights,
  type Trend,
} from "@/lib/ssa-comparison-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const TREND_ICON = { Up: TrendingUp, Down: TrendingDown, Flat: Minus } as const;
const TREND_TONE: Record<Trend, string> = {
  Up:   "text-emerald-600",
  Down: "text-rose-600",
  Flat: "text-slate-500",
};

export default function YearlyComparisonPage() {
  // Year-over-year SSA comparison is fabricated; never show it as production data.
  if (!isMockAllowed()) return <InsufficientData surface="the year-over-year SSA comparison" />;
  const insights = generateSsaImprovementInsights();

  return (
    <StubPage
      title="Yearly SSA Performance Comparison"
      subtitle="Year-over-year SSA performance, by district, cluster, and all 8 official intervention areas. Insights below identify the most-improved, most-declined, and repeated weakness patterns."
    >
      {/* Insights */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Lightbulb size={14} className="text-amber-600" />
            SSA improvement intelligence
          </h2>
          <span className="text-caption muted">{insights.length} insights</span>
        </header>
        <ul className="space-y-2.5">
          {insights.map((i) => (
            <li key={i.kind} className="rounded-xl border border-[var(--color-edify-border)] p-3 bg-[var(--color-edify-soft)]/30">
              <div className="text-body font-extrabold tracking-tight">{i.headline}</div>
              <div className="text-[11.5px] muted leading-snug mt-0.5">{i.detail}</div>
              <div className="text-[11.5px] mt-1.5">
                <span className="font-extrabold text-emerald-700">Recommendation: </span>
                <span>{i.recommendation}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* District comparison */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">District comparison (Previous FY vs Current FY)</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[780px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">District</th>
                <th scope="col" className="py-2 px-2 text-right">Prev FY</th>
                <th scope="col" className="py-2 px-2 text-right">Current FY</th>
                <th scope="col" className="py-2 px-2 text-right">Change</th>
                <th scope="col" className="py-2 px-2">Best improving</th>
                <th scope="col" className="py-2 px-2">Weakest</th>
                <th scope="col" className="py-2 px-2 text-right">Schools / Coverage</th>
                <th scope="col" className="py-2 pl-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {districtSsaComparison.map((d) => {
                const Icon = TREND_ICON[d.trend];
                return (
                  <tr key={d.district} className="hover:bg-[var(--color-edify-soft)]/30">
                    <td className="py-2 pr-2 font-extrabold">{d.district}</td>
                    <td className="py-2 px-2 text-right tabular">{d.previousFyAverage.toFixed(2)}</td>
                    <td className="py-2 px-2 text-right tabular font-extrabold">{d.currentFyAverage.toFixed(2)}</td>
                    <td className={cn("py-2 px-2 text-right tabular font-extrabold inline-flex items-center justify-end gap-0.5 w-full", TREND_TONE[d.trend])}>
                      <Icon size={10} />
                      {d.change > 0 ? `+${d.change.toFixed(2)}` : d.change.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 muted">{d.bestImprovingIntervention}</td>
                    <td className="py-2 px-2 muted">{d.weakestIntervention}</td>
                    <td className="py-2 px-2 text-right tabular">{d.schoolsAssessed} / {d.coverage}%</td>
                    <td className="py-2 pl-2">
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                        d.status === "Improving"  && "bg-emerald-100 text-emerald-700",
                        d.status === "Stable"     && "bg-sky-100     text-sky-700",
                        d.status === "Declining"  && "bg-rose-100    text-rose-700",
                      )}>{d.status}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Cluster comparison */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Cluster comparison</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px] min-w-[780px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Cluster</th>
                <th scope="col" className="py-2 px-2">District</th>
                <th scope="col" className="py-2 px-2 text-right">Prev FY</th>
                <th scope="col" className="py-2 px-2 text-right">Current FY</th>
                <th scope="col" className="py-2 px-2 text-right">Change</th>
                <th scope="col" className="py-2 px-2 text-right">Schools (Core/Client)</th>
                <th scope="col" className="py-2 px-2">Weakest</th>
                <th scope="col" className="py-2 pl-2">Focus</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {clusterSsaComparison.map((c) => {
                const Icon = TREND_ICON[c.trend];
                return (
                  <tr key={c.cluster}>
                    <td className="py-2 pr-2 font-extrabold">{c.cluster}</td>
                    <td className="py-2 px-2 muted">{c.district}</td>
                    <td className="py-2 px-2 text-right tabular">{c.previousFyAverage.toFixed(2)}</td>
                    <td className="py-2 px-2 text-right tabular font-extrabold">{c.currentFyAverage.toFixed(2)}</td>
                    <td className={cn("py-2 px-2 text-right tabular font-extrabold inline-flex items-center justify-end gap-0.5 w-full", TREND_TONE[c.trend])}>
                      <Icon size={10} />
                      {c.change > 0 ? `+${c.change.toFixed(2)}` : c.change.toFixed(2)}
                    </td>
                    <td className="py-2 px-2 text-right tabular">{c.schoolsAssessed} ({c.coreSchoolsAssessed}/{c.clientSchoolsAssessed})</td>
                    <td className="py-2 px-2 muted">{c.weakestIntervention}</td>
                    <td className="py-2 pl-2 muted">{c.recommendedFocus}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* All 8 interventions */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Intervention comparison — all 8 areas</h2>
        <ul className="space-y-2">
          {interventionSsaComparison.map((i) => {
            const Icon = TREND_ICON[i.trend];
            const widthPct = (i.currentFyAverage / 10) * 100;
            const barColor = i.currentFyAverage >= 7 ? "#10b981" : i.currentFyAverage >= 6 ? "#f59e0b" : "#ef4444";
            return (
              <li key={i.intervention} className="flex items-center gap-3 text-[12px]">
                <div className="w-[200px] font-extrabold tracking-tight shrink-0 truncate">{i.intervention}</div>
                <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${widthPct}%`, backgroundColor: barColor }} />
                </div>
                <div className="w-16 text-right tabular font-extrabold shrink-0">{i.currentFyAverage.toFixed(2)}</div>
                <div className={cn("inline-flex items-center gap-0.5 w-16 justify-end font-semibold tabular shrink-0", TREND_TONE[i.trend])}>
                  <Icon size={10} />
                  {i.change > 0 ? `+${i.change.toFixed(2)}` : i.change.toFixed(2)}
                </div>
                <div className="w-[120px] text-right muted text-caption shrink-0 truncate">Best: {i.bestDistrict}</div>
                <div className="w-[120px] text-right muted text-caption shrink-0 truncate">Weak: {i.weakestDistrict}</div>
              </li>
            );
          })}
        </ul>
      </section>
    </StubPage>
  );
}
