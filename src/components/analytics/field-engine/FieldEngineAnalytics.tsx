"use client";

// Engine-backed analytics surface (Phase 1 reference).
//
// The first analytics page where every number is computed live from the
// workflow records, changes with the filter bar, and drills into the exact
// records behind it. Proves the pattern the rest of the analytics rollout
// follows. Uses the shared filter engine + computeAnalytics + the existing
// tile-filter drilldown primitives.

import { useMemo } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import type { FilterScope } from "@/lib/filters/types";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { useActiveFilters } from "@/hooks/use-active-filters";
import { useTileFilter } from "@/components/tile-filter/use-tile-filter";
import { InteractiveTile } from "@/components/tile-filter/InteractiveTile";
import { ActiveTileFilterHeader } from "@/components/tile-filter/ActiveTileFilterHeader";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { FIELD_ANALYTICS_TILES } from "./tile-registry";
import type { AnalyticsMetric, FunnelStage, HeatmapRow } from "@/lib/analytics/types";

const REACH_KEYS = ["schoolsReached", "learnersImpacted", "teachersTrained", "schoolLeadersTrained", "districtsCovered", "clustersCovered"];
const IMPACT_KEYS = ["activitiesCompleted", "ssaImproved", "ssaDeclined", "examImproved", "mscDonorReady"];

// SSA cell tone (spec §8): 0–4 Critical, 5–6 Needs Support, 7–8 Good, 9–10 Strong.
function cellTone(score: number | undefined): { bg: string; fg: string } {
  if (score === undefined) return { bg: "var(--surface-2)", fg: "var(--text-muted)" };
  if (score >= 9) return { bg: "#0f8a5f", fg: "#ffffff" };
  if (score >= 7) return { bg: "#a7f3d0", fg: "#065f46" };
  if (score >= 5) return { bg: "#fde68a", fg: "#78350f" };
  return { bg: "#fecaca", fg: "#991b1b" };
}

export function FieldEngineAnalytics({
  filterScope,
  role,
  scopeLabel,
}: {
  filterScope: FilterScope;
  role: string;
  scopeLabel: string;
}) {
  const selection = useActiveFilters();
  const { activeFilter, isActive, setTileFilter, resetTileFilter } = useTileFilter(FIELD_ANALYTICS_TILES);

  const snapshot = useMemo(
    () => computeAnalytics({ selection, role, scopeLabel }),
    [selection, role, scopeLabel],
  );

  const byKey = useMemo(() => {
    const m = new Map<string, AnalyticsMetric>();
    for (const metric of snapshot.metrics) m.set(metric.key, metric);
    return m;
  }, [snapshot]);

  const activeMetric = activeFilter ? byKey.get(activeFilter.id) : undefined;

  return (
    <div className="space-y-4">
      <HeaderFilterBar scope={filterScope} />

      {/* Data quality */}
      {snapshot.dataQuality.notes.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-2.5">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-600 mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="t-caption font-bold uppercase tracking-wide text-amber-800">Data quality · {snapshot.dataQuality.level}</div>
              <ul className="mt-0.5 space-y-0.5">
                {snapshot.dataQuality.notes.map((n) => (
                  <li key={n} className="t-caption text-amber-900">{n}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {/* Reach KPIs */}
      <MetricGrid title="Reach" keys={REACH_KEYS} byKey={byKey} isActive={isActive} onSelect={setTileFilter} />

      {/* Drilldown — the records behind the active number */}
      {activeFilter && activeMetric && (
        <section className="card p-3.5">
          <ActiveTileFilterHeader filter={activeFilter} count={activeMetric.records.length} onReset={resetTileFilter} />
          <p className="t-caption muted mt-1">{activeMetric.definition}</p>
          <ul className="mt-3 divide-y divide-[var(--color-edify-divider)]">
            {activeMetric.records.length === 0 && (
              <li className="py-6 text-center t-caption muted inline-flex items-center gap-2 justify-center w-full"><Inbox size={14} /> No records behind this number for the current filters.</li>
            )}
            {activeMetric.records.map((r) => (
              <li key={r.id} className="py-2 flex items-center gap-3">
                <span className={"h-1.5 w-1.5 rounded-full shrink-0 " + (r.contributesToCount ? "bg-[var(--color-success)]" : "bg-[var(--text-muted)]")} />
                <div className="min-w-0 flex-1">
                  <div className="t-body font-semibold truncate">{r.title}</div>
                  {r.subtitle && <div className="t-caption muted truncate">{r.subtitle}</div>}
                </div>
                {!r.contributesToCount && <span className="t-tiny uppercase tracking-wide text-[var(--text-muted)]">excluded</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Activity pipeline funnel */}
      <PipelineFunnel stages={snapshot.pipeline} />

      {/* Impact + SSA KPIs */}
      <MetricGrid title="Activity & Improvement" keys={IMPACT_KEYS} byKey={byKey} isActive={isActive} onSelect={setTileFilter} />

      {/* SSA intervention heatmap */}
      <SsaHeatmap interventions={snapshot.ssaHeatmap.interventions} rows={snapshot.ssaHeatmap.rows} />
    </div>
  );
}

function MetricGrid({
  title, keys, byKey, isActive, onSelect,
}: {
  title: string;
  keys: string[];
  byKey: Map<string, AnalyticsMetric>;
  isActive: (id: string) => boolean;
  onSelect: (id: string | null) => void;
}) {
  const metrics = keys.map((k) => byKey.get(k)).filter(Boolean) as AnalyticsMetric[];
  return (
    <section className="space-y-2">
      <h2 className="t-tiny uppercase tracking-wide muted font-bold">{title}</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2.5">
        {metrics.map((metric) => (
          <InteractiveTile
            key={metric.key}
            active={isActive(metric.key)}
            onClick={() => onSelect(isActive(metric.key) ? null : metric.key)}
            className="card p-3 text-left"
          >
            <div className="t-caption muted font-semibold leading-tight">{metric.label}</div>
            <div className="num-hero tabular text-[22px] font-extrabold leading-none mt-1">{metric.value.toLocaleString()}</div>
            <div className="t-tiny muted mt-1">
              {metric.breakdown.verified > 0 ? `${metric.breakdown.verified.toLocaleString()} verified` : "click to drill"}
              {metric.target ? ` · exp ${metric.target.expectedCumulative.toLocaleString()} · ${metric.target.paceStatus}` : ""}
            </div>
          </InteractiveTile>
        ))}
      </div>
    </section>
  );
}

function PipelineFunnel({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(1, ...stages.map((s) => s.count));
  return (
    <section className="card p-3.5">
      <h2 className="t-body-lg font-extrabold tracking-tight">Activity pipeline</h2>
      <p className="t-caption muted">Planned → Completed (Salesforce gate) → IA Verified → Paid.</p>
      <div className="mt-3 space-y-2">
        {stages.map((s) => (
          <div key={s.key} className="flex items-center gap-3">
            <div className="w-24 shrink-0 t-caption font-semibold">{s.label}</div>
            <div className="flex-1 h-6 rounded-md bg-[var(--surface-2)] overflow-hidden">
              <div className="h-full rounded-md bg-[var(--color-edify-primary)]/85 flex items-center justify-end pr-2" style={{ width: `${Math.max(6, (s.count / max) * 100)}%` }}>
                <span className="t-caption font-bold text-white tabular">{s.count}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SsaHeatmap({ interventions, rows }: { interventions: string[]; rows: HeatmapRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="card p-3.5 overflow-x-auto">
      <h2 className="t-body-lg font-extrabold tracking-tight">SSA intervention heatmap</h2>
      <p className="t-caption muted">Average SSA score per intervention, by district (reached schools).</p>
      <table className="mt-3 w-full border-collapse text-left">
        <thead>
          <tr>
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 pr-3">District</th>
            {interventions.map((a) => (
              <th key={a} className="t-tiny muted font-semibold px-1.5 py-1.5 text-center align-bottom" style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", maxHeight: 110 }}>{a}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="t-caption font-semibold py-1 pr-3 whitespace-nowrap">{row.label}</td>
              {interventions.map((a) => {
                const v = row.scores[a];
                const tone = cellTone(v);
                return (
                  <td key={a} className="px-1 py-1 text-center">
                    <span className="inline-flex items-center justify-center w-9 h-7 rounded-md t-caption font-bold tabular" style={{ backgroundColor: tone.bg, color: tone.fg }}>
                      {v ?? "—"}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
