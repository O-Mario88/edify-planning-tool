"use client";

import { useCallback, useEffect, useState } from "react";
import { Building2, Download, Info, MapPin } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeSsaPerformanceGrouped, BeSsaGroupRow } from "@/lib/api/surfaces";
import { isFilterActive, useActiveFilters } from "@/hooks/use-active-filters";
import { applyGeographyScope } from "@/lib/filters/apply-filters";
import { cn } from "@/lib/utils";

// District SSA Performance — derived live from the backend SSA-performance grid
// (groupBy=district). Each row's average is the mean of the 8 intervention
// averages for that district; "highest weakness" is its lowest-scoring
// intervention; completion = schools assessed / schools in scope. No mock
// fallback: empty when the database has no assessed districts, error on failure.

function scoreColor(s: number) {
  if (s >= 7.5) return "text-emerald-700";
  if (s >= 6.0) return "text-amber-700";
  if (s >= 4.5) return "text-orange-700";
  return "text-rose-700";
}

function scoreEdge(s: number) {
  if (s >= 7.5) return "border-l-emerald-500";
  if (s >= 6.0) return "border-l-amber-500";
  if (s >= 4.5) return "border-l-orange-500";
  return "border-l-rose-500 bg-rose-50/30";
}

type Row = {
  rank: number;
  district: string;
  schoolsAssessed: number;
  averageScore: number;
  highestWeakness: string;
  completionRate: number;
};

function deriveRows(data: BeSsaPerformanceGrouped): Row[] {
  const labelByCode = new Map(data.interventions.map((iv) => [iv.code, iv.label]));
  const assessed = data.rows.filter(
    (r): r is BeSsaGroupRow & { overallAverage: number } => r.overallAverage != null && r.schoolsAssessed > 0,
  );
  return assessed
    .map((r) => {
      // Lowest-scoring intervention = highest weakness.
      let weakCode: string | null = null;
      let weakVal = Infinity;
      for (const iv of data.interventions) {
        const v = r.interventions[iv.code];
        if (v != null && v < weakVal) {
          weakVal = v;
          weakCode = iv.code;
        }
      }
      return {
        district: r.groupName,
        schoolsAssessed: r.schoolsAssessed,
        averageScore: r.overallAverage,
        highestWeakness: weakCode ? labelByCode.get(weakCode) ?? weakCode : "—",
        completionRate: r.schoolCount > 0 ? (r.schoolsAssessed / r.schoolCount) * 100 : 0,
      };
    })
    .sort((a, b) => b.averageScore - a.averageScore)
    .map((r, i) => ({ ...r, rank: i + 1 }));
}

export function DistrictSsaPerformanceTable() {
  const [data, setData] = useState<BeSsaPerformanceGrouped | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Header filters → data. FY goes to the backend (it owns the FY window);
  // district/region scope the district-keyed rows client-side (region derives
  // from the district via the geography source of truth).
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
        setError(j?.error ?? "Could not load district SSA performance.");
        setData(null);
      } else {
        setData(j);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setData(null);
    }
    setLoading(false);
  }, [fy]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = data
    ? deriveRows({
        ...data,
        rows: applyGeographyScope(data.rows, selection, { district: (r) => r.groupName }),
      })
    : null;

  return (
    <SectionCard
      icon={<Building2 size={13} />}
      title="District SSA Performance"
      actions={
        <div className="flex items-center gap-2">
          <Info size={13} className="text-[var(--color-edify-muted)]" />
          <button type="button" className="btn btn-sm" disabled={!rows || rows.length === 0}>
            <Download size={12} />
            Export
          </button>
        </div>
      }
    >
      {loading ? (
        <LoadingState message="Loading district SSA performance…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState
          title="No assessed districts yet"
          message="District SSA performance appears once schools in scope have a completed self-assessment."
        />
      ) : (
        <>
          {/* Mobile-stacked variant — one card per district, color-coded
              left edge by score tier, hero score on the right. */}
          <div className="md:hidden space-y-2">
            {rows.map((d) => (
              <div
                key={d.district}
                className={cn(
                  "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-3 space-y-2",
                  scoreEdge(d.averageScore),
                )}
              >
                <div className="flex items-start gap-2.5">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white text-[11px] font-extrabold grid place-items-center shrink-0 shadow-sm">
                    {d.rank}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-bold leading-tight truncate text-slate-900 inline-flex items-center gap-1.5">
                      <MapPin size={11} className="text-[var(--color-edify-muted)]" />
                      {d.district}
                    </div>
                    <div className="text-caption muted leading-tight mt-0.5 tabular">
                      {d.schoolsAssessed} schools assessed · {d.completionRate.toFixed(1)}% completion
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className={cn("text-[20px] font-extrabold tabular leading-none", scoreColor(d.averageScore))}>
                      {d.averageScore.toFixed(2)}
                    </div>
                    <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">/10 SSA</div>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-2 flex-wrap text-caption">
                  <span className="text-slate-700 leading-snug">
                    <span className="muted font-semibold">Weakness:</span>{" "}
                    <span className="font-semibold">{d.highestWeakness}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop table — gradient header, hover rows. */}
          <div className="hidden md:block overflow-x-auto -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600">
                  <th scope="col" className="text-left font-bold py-2 px-2">#</th>
                  <th scope="col" className="text-left font-bold py-2 px-2">District</th>
                  <th scope="col" className="text-right font-bold py-2 px-2">Schools</th>
                  <th scope="col" className="text-right font-bold py-2 px-2">Avg Score ↓</th>
                  <th scope="col" className="text-left font-bold py-2 px-2">Highest Weakness</th>
                  <th scope="col" className="text-right font-bold py-2 px-2">Completion</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d, idx) => {
                  const last = idx === rows.length - 1;
                  return (
                    <tr
                      key={d.district}
                      className={cn("transition-colors hover:bg-[var(--color-edify-soft)]/40", !last && "border-b border-[#eef2f4]")}
                    >
                      <td className="py-2 px-2 font-extrabold tabular">{d.rank}</td>
                      <td className="py-2 px-2 font-semibold whitespace-nowrap">{d.district}</td>
                      <td className="py-2 px-2 text-right tabular">{d.schoolsAssessed}</td>
                      <td className={cn("py-2 px-2 text-right tabular text-[13px] font-extrabold", scoreColor(d.averageScore))}>
                        {d.averageScore.toFixed(2)}
                      </td>
                      <td className="py-2 px-2 muted">{d.highestWeakness}</td>
                      <td className="py-2 px-2 text-right tabular">{d.completionRate.toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-3 text-[11px] muted">
            Showing 1 to {rows.length} of {rows.length} districts
          </div>
        </>
      )}
    </SectionCard>
  );
}
