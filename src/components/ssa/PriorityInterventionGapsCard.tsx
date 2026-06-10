"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, MapPin } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped } from "@/lib/api/surfaces";
import { isFilterActive, useActiveFilters } from "@/hooks/use-active-filters";
import { applyGeographyScope } from "@/lib/filters/apply-filters";
import { cn } from "@/lib/utils";

// Priority intervention gaps — district × intervention heatmap, live from the
// backend SSA grid (groupBy=district). No mock fallback: empty when nothing is
// assessed, error on failure.

// Short labels for narrow cell headers, keyed by backend intervention code.
const SHORT_LABEL: Record<string, string> = {
  CHRIST_LIKE_BEHAVIOR: "Christ-like",
  EXPOSURE_TO_WORD_OF_GOD: "Word",
  LEADERSHIP_BEST_PRACTICE: "Leadership",
  TEACHING_ENVIRONMENT: "Teaching",
  LEARNING_ENVIRONMENT: "Learning",
  GOVERNMENT_REQUIREMENTS: "Govt",
  FEES_BUDGET_ACCOUNTS: "Fees",
  ENROLLMENT: "Enrollment",
};

function cellTone(score: number) {
  if (score >= 7.5) return "bg-emerald-100 text-emerald-800";
  if (score >= 6.0) return "bg-amber-100 text-amber-800";
  if (score >= 4.5) return "bg-orange-100 text-orange-800";
  return "bg-rose-100 text-rose-800";
}

function rowOverallTone(scores: (number | null)[]): { chip: string; ring: string } {
  const present = scores.filter((s): s is number => s != null);
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : 0;
  if (avg >= 7.5) return { chip: "bg-emerald-100 text-emerald-800", ring: "ring-emerald-200" };
  if (avg >= 6.0) return { chip: "bg-amber-100   text-amber-800", ring: "ring-amber-200" };
  if (avg >= 4.5) return { chip: "bg-orange-100  text-orange-800", ring: "ring-orange-200" };
  return { chip: "bg-rose-100    text-rose-800", ring: "ring-rose-200" };
}

type Col = { code: string; label: string; short: string };
type HeatRow = { district: string; scores: (number | null)[] };

export function PriorityInterventionGapsCard() {
  const [raw, setRaw] = useState<BeSsaPerformanceGrouped | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Header filters → data. FY goes to the backend; district/region scope the
  // district-keyed heatmap rows client-side (region derives from the district).
  const selection = useActiveFilters();
  const fy = isFilterActive(selection.fy) ? selection.fy : undefined;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/analytics/ssa-performance?groupBy=district&schoolType=all${fy ? `&fy=${encodeURIComponent(fy)}` : ""}`,
        { credentials: "include" },
      );
      const j = (await res.json()) as (BeSsaPerformanceGrouped & { live?: boolean; error?: string }) | null;
      if (!res.ok || !j || j.live === false) {
        setError(j?.error ?? "Could not load intervention gaps.");
        setRaw(null);
      } else {
        setRaw(j);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setRaw(null);
    }
    setLoading(false);
  }, [fy]);

  useEffect(() => {
    void load();
  }, [load]);

  const data = (() => {
    if (!raw) return null;
    const cols: Col[] = raw.interventions.map((iv) => ({
      code: iv.code,
      label: iv.label,
      short: SHORT_LABEL[iv.code] ?? iv.label,
    }));
    const rows: HeatRow[] = applyGeographyScope(raw.rows, selection, { district: (r) => r.groupName })
      .filter((r) => r.schoolsAssessed > 0)
      .map((r) => ({ district: r.groupName, scores: cols.map((c) => r.interventions[c.code] ?? null) }));
    return { cols, rows };
  })();

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="Priority Intervention Gaps by District"
      subtitle="Interventions (Average Score out of 10) — colored cells flag gaps; lower is worse."
    >
      {loading ? (
        <LoadingState message="Loading intervention gaps…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data || data.rows.length === 0 ? (
        <EmptyState
          title="No assessed districts yet"
          message="The intervention gap heatmap appears once schools in scope have a completed self-assessment."
        />
      ) : (
        <>
          {/* Mobile-stacked variant — one card per district. */}
          <div className="md:hidden space-y-2.5">
            {data.rows.map((row) => {
              const tone = rowOverallTone(row.scores);
              const present = row.scores.filter((s): s is number => s != null);
              const avg = present.length ? +(present.reduce((a, b) => a + b, 0) / present.length).toFixed(1) : 0;
              return (
                <div key={row.district} className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[13.5px] font-extrabold leading-tight text-slate-900 inline-flex items-center gap-1.5">
                        <MapPin size={11} className="text-[var(--color-edify-muted)]" />
                        {row.district}
                      </div>
                      <div className="text-caption muted font-semibold mt-0.5">District average across all 8 interventions</div>
                    </div>
                    <span className={cn("inline-flex items-center justify-center min-w-[54px] h-8 px-2.5 rounded-lg text-body-lg font-extrabold tabular ring-1", tone.chip, tone.ring)}>
                      {avg.toFixed(1)}
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-1.5">
                    {data.cols.map((c, i) => {
                      const score = row.scores[i];
                      return (
                        <div key={c.code} title={c.label} className="rounded-md bg-[var(--color-edify-soft)]/30 px-1.5 py-1.5 text-center">
                          <div className="text-[9px] font-bold uppercase tracking-tight text-slate-500 truncate">{c.short}</div>
                          <div className={cn("mt-0.5 inline-flex items-center justify-center min-w-[36px] h-6 px-1.5 rounded-md text-[11px] font-extrabold tabular", score == null ? "bg-slate-100 text-slate-400" : cellTone(score))}>
                            {score == null ? "—" : score.toFixed(1)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Desktop heatmap table. */}
          <div className="hidden md:block overflow-x-auto -mx-1 px-1">
            <table className="w-full">
              <thead>
                <tr>
                  <th scope="col" className="text-left text-[10px] muted font-bold uppercase tracking-wide pl-1.5 pr-2 pb-1.5">
                    District
                  </th>
                  {data.cols.map((c) => (
                    <th key={c.code} className="px-1 pb-1.5 text-center text-[9.5px] muted font-bold align-bottom" title={c.label}>
                      <span className="inline-block max-w-[72px] leading-tight">{c.short}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.district}>
                    <td className="text-[12px] font-semibold pl-1.5 pr-2 py-1">{row.district}</td>
                    {row.scores.map((s, i) => (
                      <td key={i} className="px-1 py-1">
                        <div className={cn("h-9 rounded-md grid place-items-center text-[11.5px] font-bold tabular", s == null ? "bg-slate-100 text-slate-400" : cellTone(s))}>
                          {s == null ? "—" : s.toFixed(1)}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </SectionCard>
  );
}
