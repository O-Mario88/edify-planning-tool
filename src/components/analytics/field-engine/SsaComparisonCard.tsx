"use client";

// SSA performance comparison — Core and Client viewed separately (never
// benchmarked against each other), compared within a segment by a role-gated
// dimension (FY / district / intervention; + CCEO / region for leadership).

import { useMemo, useState } from "react";
import { useActiveFilters } from "@/hooks/use-active-filters";
import {
  computeSsaComparison,
  ssaDimensionsForRole,
  SSA_DIMENSION_LABEL,
  type SsaDimension,
  type SsaSegment,
} from "@/lib/analytics/ssa-comparison";
import { cn } from "@/lib/utils";

// SSA band tone (spec §8): 0–4 Critical, 5–6 Needs Support, 7–8 Good, 9–10 Strong.
function band(score: number): { bar: string; fg: string } {
  if (score >= 9) return { bar: "#0f8a5f", fg: "#0f8a5f" };
  if (score >= 7) return { bar: "#34b27b", fg: "#0f7a52" };
  if (score >= 5) return { bar: "#e0a93b", fg: "#92400e" };
  return { bar: "#e0697a", fg: "#991b1b" };
}

export function SsaComparisonCard({ role }: { role: string }) {
  const selection = useActiveFilters();
  const dims = useMemo(() => ssaDimensionsForRole(role), [role]);
  const [segment, setSegment] = useState<SsaSegment>("core");
  const [dimension, setDimension] = useState<SsaDimension>(dims[0] ?? "district");

  const comparison = useMemo(
    () => computeSsaComparison({ segment, dimension, selection }),
    [segment, dimension, selection],
  );

  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="t-body-lg font-extrabold tracking-tight">SSA performance</h2>
        <span className="t-caption muted">{segment === "core" ? "Core schools" : "Client schools"} · {SSA_DIMENSION_LABEL[dimension]}</span>
        {/* Segment toggle — Core and Client are never compared to each other */}
        <div role="tablist" aria-label="School segment" className="ml-auto inline-flex rounded-lg border border-[var(--color-edify-border)] p-0.5 bg-[var(--color-edify-soft)]/40">
          {(["core", "client"] as SsaSegment[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={segment === s}
              onClick={() => setSegment(s)}
              className={cn(
                "px-2.5 h-7 rounded-md t-caption font-semibold capitalize transition-colors",
                segment === s ? "bg-white text-[var(--color-edify-text)] shadow-sm" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Role-gated dimension chips */}
      <div className="flex items-center gap-1.5 flex-wrap mt-2.5">
        {dims.map((d) => (
          <button
            key={d}
            onClick={() => setDimension(d)}
            className={cn(
              "h-7 px-2.5 rounded-full t-caption font-semibold border transition-colors",
              dimension === d
                ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]"
                : "border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
            )}
          >
            {SSA_DIMENSION_LABEL[d]}
          </button>
        ))}
      </div>

      {/* Comparison bars */}
      <div className="mt-3 space-y-1.5">
        {comparison.rows.length === 0 ? (
          <p className="t-caption muted py-4 text-center">No {segment}-school SSA data in the current scope.</p>
        ) : (
          comparison.rows.map((r) => {
            const tone = band(r.avgScore);
            return (
              <div key={r.group} className="flex items-center gap-3">
                <div className="w-40 shrink-0 t-caption font-semibold truncate" title={r.group}>{r.group}</div>
                <div className="flex-1 h-6 rounded-md bg-[var(--surface-2)] overflow-hidden">
                  <div className="h-full rounded-md flex items-center justify-end pr-2" style={{ width: `${Math.max(8, (r.avgScore / 10) * 100)}%`, backgroundColor: tone.bar }}>
                    <span className="t-caption font-bold text-white tabular">{r.avgScore}</span>
                  </div>
                </div>
                <div className="w-16 shrink-0 t-tiny muted text-right tabular">{r.schoolCount} sch.</div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
