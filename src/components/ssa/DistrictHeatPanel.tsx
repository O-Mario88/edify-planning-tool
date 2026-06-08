"use client";

import { useCallback, useEffect, useState } from "react";
import { Map } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped } from "@/lib/api/surfaces";
import { cn } from "@/lib/utils";

// District performance heat panel — per-district overall SSA score, live from
// the backend SSA grid (groupBy=district). No mock fallback: empty when nothing
// is assessed, error on failure.

type PerformanceStatus = "Strong" | "Fair" | "Weak" | "Critical";
type Tile = { district: string; score: number; status: PerformanceStatus };

const tileTone: Record<PerformanceStatus, string> = {
  Strong: "bg-emerald-50 border-emerald-200",
  Fair: "bg-amber-50 border-amber-200",
  Weak: "bg-orange-50 border-orange-200",
  Critical: "bg-rose-50 border-rose-200",
};
const labelTone: Record<PerformanceStatus, string> = {
  Strong: "text-emerald-700",
  Fair: "text-amber-700",
  Weak: "text-orange-700",
  Critical: "text-rose-700",
};

function statusOf(score: number): PerformanceStatus {
  if (score > 7.5) return "Strong";
  if (score >= 6.0) return "Fair";
  if (score >= 4.0) return "Weak";
  return "Critical";
}

function deriveTiles(data: BeSsaPerformanceGrouped): Tile[] {
  return data.rows
    .filter((r): r is typeof r & { overallAverage: number } => r.overallAverage != null && r.schoolsAssessed > 0)
    .map((r) => ({ district: r.groupName, score: r.overallAverage, status: statusOf(r.overallAverage) }))
    .sort((a, b) => b.score - a.score);
}

export function DistrictHeatPanel() {
  const [tiles, setTiles] = useState<Tile[] | null>(null);
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
        setError(j?.error ?? "Could not load district heat panel.");
        setTiles(null);
      } else {
        setTiles(deriveTiles(j));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setTiles(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SectionCard title="District Performance Heat Panel">
      {loading ? (
        <LoadingState message="Loading district heat panel…" compact />
      ) : error ? (
        <ErrorState message={error} onRetry={load} compact />
      ) : !tiles || tiles.length === 0 ? (
        <EmptyState
          compact
          title="No assessed districts yet"
          message="District performance tiles appear once schools in scope have a completed self-assessment."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            {tiles.map((t) => (
              <div key={t.district} className={cn("rounded-xl border p-2.5 flex items-center gap-2", tileTone[t.status])}>
                <span className="w-9 h-9 rounded-md bg-white/70 grid place-items-center text-[var(--color-edify-muted)] shrink-0">
                  <Map size={14} />
                </span>
                <div className="leading-tight min-w-0">
                  <div className="text-[11px] muted font-semibold">{t.district}</div>
                  <div className="text-[18px] font-extrabold tabular leading-none">{t.score.toFixed(2)}</div>
                  <div className={cn("text-caption font-bold mt-0.5", labelTone[t.status])}>{t.status}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3 pt-3 border-t border-[#eef2f4] flex flex-wrap items-center gap-x-3 gap-y-1.5 text-caption muted">
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
              &lt; 4.0
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-500" />
              4.0 – 6.0
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
              6.0 – 7.5
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              &gt; 7.5
            </span>
          </div>
        </>
      )}
    </SectionCard>
  );
}
