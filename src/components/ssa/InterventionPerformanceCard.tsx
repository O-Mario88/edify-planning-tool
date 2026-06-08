"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Info } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped } from "@/lib/api/surfaces";
import { cn } from "@/lib/utils";

// 8 Intervention Performance Overview — portfolio-wide average for each of the
// 8 interventions, computed live from the backend SSA grid (weighted by schools
// assessed per district). No mock fallback: empty when nothing is assessed,
// error on failure.

type Perf = "High" | "Medium" | "Low";
type Row = { rank: number; label: string; score: number; performance: Perf };

const perfPill: Record<Perf, string> = {
  High: "bg-emerald-100 text-emerald-700",
  Medium: "bg-amber-100 text-amber-700",
  Low: "bg-rose-100 text-rose-700",
};
const barColor: Record<Perf, string> = {
  High: "#16a34a",
  Medium: "#f59e0b",
  Low: "#ef4444",
};

function perfOf(score: number): Perf {
  if (score >= 7.5) return "High";
  if (score >= 5.5) return "Medium";
  return "Low";
}

function deriveRows(data: BeSsaPerformanceGrouped): Row[] {
  return data.interventions
    .map((iv) => {
      // School-weighted average of this intervention across districts.
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
    .map((r, i) => ({ rank: i + 1, label: r.label, score: r.score, performance: perfOf(r.score) }));
}

export function InterventionPerformanceCard() {
  const [rows, setRows] = useState<Row[] | null>(null);
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
        setError(j?.error ?? "Could not load intervention performance.");
        setRows(null);
      } else {
        setRows(deriveRows(j));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setRows(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="8 Intervention Performance Overview"
      actions={<Info size={13} className="text-[var(--color-edify-muted)]" />}
    >
      {loading ? (
        <LoadingState message="Loading intervention performance…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState
          title="No intervention scores yet"
          message="Intervention averages appear once schools in scope have a completed self-assessment."
        />
      ) : (
        <>
          <div className="grid grid-cols-[24px_2fr_1fr_88px_88px] gap-x-2 text-[11px] muted font-semibold uppercase tracking-wide pb-2 border-b border-[#eef2f4]">
            <div />
            <div>
              Intervention <span className="font-medium normal-case">(Score out of 10)</span>
            </div>
            <div />
            <div className="text-right">Average Score</div>
            <div className="text-center">Performance</div>
          </div>

          <div className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((r) => (
              <div key={r.label} className="grid grid-cols-[24px_2fr_1fr_88px_88px] gap-x-2 items-center py-2.5">
                <div className="w-5 h-5 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-caption font-extrabold tabular">
                  {r.rank}
                </div>
                <div className="text-body font-semibold truncate">{r.label}</div>
                <div className="h-2.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${(r.score / 10) * 100}%`, background: barColor[r.performance] }}
                  />
                </div>
                <div className="text-right tabular text-body font-bold">{r.score.toFixed(2)}</div>
                <div className="text-center">
                  <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold", perfPill[r.performance])}>
                    {r.performance}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-2 text-caption muted text-center">Score (out of 10)</div>
        </>
      )}
    </SectionCard>
  );
}
