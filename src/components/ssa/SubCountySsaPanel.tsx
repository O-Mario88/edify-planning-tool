"use client";

// District → Sub-county SSA drill-down. Appears ONLY when a district is
// selected in the header filter, and shows SSA performance for the sub-counties
// INSIDE that district — never a sub-county outside it. Backend-driven
// (/analytics/ssa-performance-grouped?groupBy=subCounty&district=<name>), so the
// rows are real averages over the scoped, filtered schools.

import { useCallback, useEffect, useState } from "react";
import { MapPinned } from "lucide-react";
import { isFilterActive, useActiveFilters } from "@/hooks/use-active-filters";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeSsaPerformanceGrouped, BeSsaGroupRow } from "@/lib/api/surfaces";

function tone(score: number | null): string {
  if (score == null) return "text-slate-400";
  if (score < 5) return "text-rose-600";
  if (score < 7) return "text-amber-600";
  if (score < 9) return "text-emerald-600";
  return "text-emerald-700";
}

function severityLabel(score: number | null): string {
  if (score == null) return "—";
  if (score < 5) return "Critical";
  if (score < 7) return "Needs Support";
  if (score < 9) return "Good";
  return "Strong";
}

function weakest(row: BeSsaGroupRow, interventions: { code: string; label: string }[]): string {
  let min: { label: string; v: number } | null = null;
  for (const i of interventions) {
    const v = row.interventions[i.code];
    if (v != null && (min == null || v < min.v)) min = { label: i.label, v };
  }
  return min ? `${min.label} (${min.v.toFixed(1)})` : "—";
}

export function SubCountySsaPanel() {
  const selection = useActiveFilters();
  const district = isFilterActive(selection.district) ? selection.district : undefined;
  const fy = isFilterActive(selection.fy) ? selection.fy : undefined;
  const [data, setData] = useState<BeSsaPerformanceGrouped | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!district) { setData(null); return; }
    setLoading(true); setError(null);
    try {
      const res = await fetch(
        `/api/analytics/ssa-performance?groupBy=subCounty&district=${encodeURIComponent(district)}${fy ? `&fy=${encodeURIComponent(fy)}` : ""}`,
        { credentials: "include" },
      );
      const j = await res.json();
      if (j.live) setData(j); else setError(j.error || "Could not load sub-county performance");
    } catch { setError("Could not reach the server"); }
    setLoading(false);
  }, [district, fy]);

  useEffect(() => { void load(); }, [load]);

  // Only a district-scoped drill-down — hidden until a district is chosen.
  if (!district) return null;

  const rows = data ? [...data.rows].filter((r) => r.schoolsAssessed > 0).sort((a, b) => (b.overallAverage ?? -1) - (a.overallAverage ?? -1)) : [];

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <MapPinned size={14} /> SSA Performance by Sub-county <span className="muted font-semibold">· {district}</span>
        </h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : rows.length === 0 ? (
        <EmptyState compact title="No sub-county SSA yet" message={`No completed SSA scores for sub-counties in ${district} yet.`} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)]">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider font-bold muted border-b border-[var(--color-edify-divider)]">
                <th className="px-2.5 py-2">Sub-county</th>
                <th className="px-2.5 py-2 text-right">Schools</th>
                <th className="px-2.5 py-2 text-right">Assessed</th>
                <th className="px-2.5 py-2 text-right">Avg SSA</th>
                <th className="px-2.5 py-2">Severity</th>
                <th className="px-2.5 py-2">Weakest intervention</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {rows.map((r) => (
                <tr key={r.groupId} className="hover:bg-[var(--color-edify-soft)]/40">
                  <td className="px-2.5 py-2 font-extrabold">{r.groupName}</td>
                  <td className="px-2.5 py-2 text-right tabular">{r.schoolCount}</td>
                  <td className="px-2.5 py-2 text-right tabular">{r.schoolsAssessed}</td>
                  <td className={cn("px-2.5 py-2 text-right tabular font-extrabold", tone(r.overallAverage))}>{r.overallAverage?.toFixed(1) ?? "—"}</td>
                  <td className="px-2.5 py-2"><span className={cn("text-[10.5px] font-bold", tone(r.overallAverage))}>{severityLabel(r.overallAverage)}</span></td>
                  <td className="px-2.5 py-2 muted">{weakest(r, data!.interventions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
