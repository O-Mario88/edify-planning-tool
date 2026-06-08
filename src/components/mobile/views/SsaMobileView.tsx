"use client";

import { useCallback, useEffect, useState } from "react";
import { TrendingUp } from "lucide-react";
import {
  MobileSubpageShell,
  MobileSectionCard,
} from "@/components/mobile/views/MobileSubpageShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped } from "@/lib/api/surfaces";
import { SsaPerformanceGrid } from "@/components/ssa/SsaPerformanceGrid";
import { InterventionImprovementGrid } from "@/components/ssa/InterventionImprovementGrid";
import { SupportImprovementCard } from "@/components/analytics/SupportImprovementCard";

function barColor(score: number) {
  if (score >= 7.0) return "#10b981";
  if (score >= 6.0) return "#f59e0b";
  return "#ef4444";
}

type InterventionRow = { rank: number; label: string; score: number };
type DistrictRow = { rank: number; district: string; schoolsAssessed: number; averageScore: number; completionRate: number };

function deriveInterventions(data: BeSsaPerformanceGrouped): InterventionRow[] {
  return data.interventions
    .map((iv) => {
      let sum = 0;
      let weight = 0;
      for (const r of data.rows) {
        const v = r.interventions[iv.code];
        if (v != null && r.schoolsAssessed > 0) {
          sum += v * r.schoolsAssessed;
          weight += r.schoolsAssessed;
        }
      }
      return { label: iv.label, score: weight > 0 ? sum / weight : null };
    })
    .filter((r): r is { label: string; score: number } => r.score != null)
    .sort((a, b) => b.score - a.score)
    .map((r, i) => ({ rank: i + 1, label: r.label, score: r.score }));
}

function deriveDistricts(data: BeSsaPerformanceGrouped): DistrictRow[] {
  return data.rows
    .filter((r): r is typeof r & { overallAverage: number } => r.overallAverage != null && r.schoolsAssessed > 0)
    .map((r) => ({
      district: r.groupName,
      schoolsAssessed: r.schoolsAssessed,
      averageScore: r.overallAverage,
      completionRate: r.schoolCount > 0 ? (r.schoolsAssessed / r.schoolCount) * 100 : 0,
    }))
    .sort((a, b) => b.averageScore - a.averageScore)
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

export function SsaMobileView() {
  const [data, setData] = useState<BeSsaPerformanceGrouped | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/analytics/ssa-performance?groupBy=district&schoolType=all", {
        credentials: "include",
      });
      const j = (await res.json()) as (BeSsaPerformanceGrouped & { live?: boolean; error?: string }) | null;
      if (!res.ok || !j || j.live === false) {
        setError(j?.error ?? "Could not load SSA performance.");
        setData(null);
      } else {
        setData(j);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setData(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const interventions = data ? deriveInterventions(data) : [];
  const districts = data ? deriveDistricts(data) : [];

  return (
    <MobileSubpageShell
      title="SSA Performance"
      subtitle="School self-assessment intelligence across the portfolio"
    >
      {/* Backend-driven truth layer (same as desktop): the 8-intervention SSA
          performance grid, FY-over-FY improvement, and support→improvement. */}
      <SsaPerformanceGrid />
      <InterventionImprovementGrid />
      <SupportImprovementCard />

      {/* Intervention scores — live portfolio-wide averages. */}
      <MobileSectionCard title="Intervention Performance" subtitle="Average score across the 8 SSA areas">
        {loading ? (
          <LoadingState message="Loading…" compact />
        ) : error ? (
          <ErrorState message={error} onRetry={load} compact />
        ) : interventions.length === 0 ? (
          <EmptyState compact title="No scores yet" message="Intervention averages appear once schools are assessed." />
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {interventions.map((row) => (
              <li key={row.label} className="px-3 py-2 flex items-center gap-2">
                <span className="text-caption muted font-bold tabular shrink-0 w-5">#{row.rank}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-[11.5px] font-semibold leading-tight truncate">{row.label}</div>
                  <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${(row.score / 10) * 100}%`, backgroundColor: barColor(row.score) }} />
                  </div>
                </div>
                <span className="text-[11.5px] font-extrabold tabular shrink-0 w-10 text-right">{row.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
      </MobileSectionCard>

      {/* District performance list — live, ranked by average SSA. */}
      <MobileSectionCard title="Districts" subtitle="Ranked by average SSA" ctaLabel="View All" ctaHref="#districts">
        {loading ? (
          <LoadingState message="Loading…" compact />
        ) : error ? (
          <ErrorState message={error} onRetry={load} compact />
        ) : districts.length === 0 ? (
          <EmptyState compact title="No assessed districts yet" message="District performance appears once schools are assessed." />
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {districts.map((d) => (
              <li key={d.district} className="px-3 py-2.5 flex items-center gap-3">
                <span className="text-caption muted font-bold tabular shrink-0 w-6">#{d.rank}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight">{d.district}</div>
                  <div className="text-caption muted truncate">
                    {d.schoolsAssessed} schools · {d.completionRate.toFixed(0)}% complete
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular leading-none">{d.averageScore.toFixed(2)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </MobileSectionCard>

      <div className="muted text-caption inline-flex items-center gap-1 px-1">
        <TrendingUp size={11} />
        Portfolio-wide SSA averages, scoped to your role.
      </div>
    </MobileSubpageShell>
  );
}
