"use client";

// Engine-backed analytics surface — the data-room.
//
// Every number is computed live from the workflow records (computeAnalytics),
// changes with the filter bar, and drills into the exact records behind it.
// The headline reach metrics (schools reached / learners / teachers / districts /
// SSA improved) now live in the scoped "My Contribution" lens + the live backend
// band above this on /analytics, so this surface drops the duplicate hero band and
// owns the UNIQUE views: charts grid (line / donut / funnel / bar) → SSA heatmap +
// core/client comparison → grouped operational panels (verification / payment /
// exam / MSC) → district ranking + MSC funnel. Premium, dense, organized.

import { useMemo } from "react";
import { AlertTriangle, Inbox, Download } from "lucide-react";
import { ALL_SENTINEL, type FilterSelection } from "@/lib/filters/types";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type { AnalyticsSnapshot, AnalyticsMetric } from "@/lib/analytics/types";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { useActiveFilters } from "@/hooks/use-active-filters";
import { useTileFilter } from "@/components/tile-filter/use-tile-filter";
import { ActiveTileFilterHeader } from "@/components/tile-filter/ActiveTileFilterHeader";
import { computeAnalytics } from "@/lib/analytics/compute-analytics";
import { SsaComparisonCard } from "./SsaComparisonCard";
import { FIELD_ANALYTICS_TILES } from "./tile-registry";
import { MomentumChart, VerificationDonut, PipelineFunnel, InterventionRankBar, SsaHeatmap } from "./charts";
import { cn } from "@/lib/utils";

// Compact grouped panels — replaces the flat tile-wall with organized lists.
const PANELS: { title: string; keys: string[] }[] = [
  { title: "Reach & improvement", keys: ["coreSchoolsReached", "schoolLeadersTrained", "clustersCovered", "ssaDeclined", "examImproved", "mscDonorReady"] },
  { title: "Verification & evidence", keys: ["evidenceUploaded", "evidenceAccepted", "evidenceReturned", "evidenceMissing", "sfEntered", "iaVerified", "sfMissing", "selfVerification"] },
  { title: "Payment", keys: ["paymentsAwaitingPl", "paymentsSentToAccountant", "paymentsPaid", "paymentsBlocked"] },
  { title: "Exam & MSC", keys: ["examResultsCollected", "examMissing", "examCollectionRate", "mscSubmitted", "mscPendingReview"] },
];

export function FieldEngineAnalytics({
  role,
  scopeLabel,
  personal = false,
}: {
  role: string;
  scopeLabel: string;
  /** Personal-portfolio mode (CCEO, spec §22): the engine is already
   *  viewer-scoped via `role`; this leads with a "My portfolio" metric
   *  strip and hides the country-wide comparison sections. */
  personal?: boolean;
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
  const toggle = (key: string) => setTileFilter(isActive(key) ? null : key);
  const reachMetric = byKey.get("schoolsReached");

  // computeAnalytics runs over a ~12-school MOCK universe and contradicts the
  // live backend band shown above this surface on /analytics. In production show
  // only the live band; withhold this mock-computed body.
  if (!isMockAllowed()) return <InsufficientData surface="the analytics data-room" />;

  return (
    <div className="space-y-3.5">
      {/* Lead row — data-quality strip with Export on the same line.
          The live filter bar lives in the page's <PageHeader> (filterBar
          slot); Export stays in this component because the CSV is built
          from the snapshot computed here. */}
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <DataQualityStrip score={snapshot.dataQualityScore} notes={snapshot.dataQuality.notes} />
        </div>
        <button
          type="button"
          onClick={() => exportSnapshotCsv(snapshot, selection, scopeLabel)}
          className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-card)] text-[12px] font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40 shrink-0"
        >
          <Download size={13} /> Export
        </button>
      </div>

      {/* Personal portfolio strip (CCEO §22) — my schools, gaps, splits,
          target pace and cost, all from the viewer-scoped snapshot. */}
      {personal && (
        <MetricStrip
          title={`My portfolio — FY ${snapshot.fyId}`}
          metrics={buildPersonalCells(byKey)}
          columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6"
        />
      )}

      {/* Drilldown — records behind the active number */}
      {activeFilter && activeMetric && (
        <DrilldownPanel metric={activeMetric} filter={activeFilter} onReset={resetTileFilter} />
      )}

      {/* Charts — row A */}
      <div className="grid grid-cols-12 gap-3.5">
        <ChartCard className="col-span-12 lg:col-span-7" title="Activity momentum" subtitle="Completed activities by month (Salesforce-gated).">
          <MomentumChart data={snapshot.trend} height={236} />
        </ChartCard>
        <ChartCard className="col-span-12 lg:col-span-5" title="Reach → verification" subtitle="Where reached schools sit in the evidence funnel.">
          {reachMetric ? <VerificationDonut breakdown={reachMetric.breakdown} height={236} /> : null}
        </ChartCard>
      </div>

      {/* Charts — row B */}
      <div className="grid grid-cols-12 gap-3.5">
        <ChartCard className="col-span-12 lg:col-span-5" title="Activity pipeline" subtitle="Planned → Completed → IA Verified → Paid.">
          <PipelineFunnel stages={snapshot.pipeline} />
        </ChartCard>
        <ChartCard className="col-span-12 lg:col-span-7" title="SSA by intervention" subtitle="Average score across reached schools, ranked.">
          <InterventionRankBar interventions={snapshot.ssaHeatmap.interventions} rows={snapshot.ssaHeatmap.rows} height={260} />
        </ChartCard>
      </div>

      {/* SSA heatmap (premium grid) */}
      <ChartCard title="SSA performance heatmap" subtitle="Average score · district × intervention. Darker green is stronger.">
        <SsaHeatmap interventions={snapshot.ssaHeatmap.interventions} rows={snapshot.ssaHeatmap.rows} />
      </ChartCard>

      {/* Core vs Client SSA performance — segments separate, role-gated */}
      <SsaComparisonCard role={role} />

      {/* Operational metrics — compact grouped panels (drillable) */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3.5">
        {PANELS.map((p) => (
          <StatPanel key={p.title} title={p.title} metrics={p.keys.map((k) => byKey.get(k)).filter(Boolean) as AnalyticsMetric[]} isActive={isActive} onSelect={toggle} />
        ))}
      </div>

      {/* District ranking + MSC funnel. The district-vs-district ranking is
          a country-wide view — personal mode (CCEO portfolio) drops it. */}
      <div className="grid grid-cols-12 gap-3.5">
        {!personal && (
          <div className="col-span-12 lg:col-span-7"><DistrictComparison rows={snapshot.districtComparison} /></div>
        )}
        <ChartCard className={cn("col-span-12", personal ? "" : "lg:col-span-5")} title="MSC story workflow" subtitle="Submitted → PL Reviewed → Verified → Donor-Ready.">
          <PipelineFunnel stages={snapshot.mscFunnel} />
        </ChartCard>
      </div>
    </div>
  );
}

// ── Personal portfolio cells (CCEO §22) ──
// Reads the viewer-scoped snapshot metrics; every cell traces to an
// AnalyticsMetric the drilldown/export already understand.
function buildPersonalCells(byKey: Map<string, AnalyticsMetric>): MetricCell[] {
  const m = (k: string) => byKey.get(k);
  const v = (k: string) => m(k)?.value ?? 0;
  const ofPlanned = (k: string): string | undefined => {
    const mx = m(k);
    return mx ? `of ${mx.breakdown.planned} planned` : undefined;
  };
  // Red flags = the needs-attention states on MY portfolio.
  const redFlags = v("ssaDeclined") + v("evidenceReturned") + v("paymentsBlocked");
  const target = m("activitiesCompleted")?.target;
  const cost = v("plannedCost");
  const costLabel = cost >= 1_000_000 ? `${(cost / 1_000_000).toFixed(1)}M` : cost.toLocaleString();

  const cells: (MetricCell | null)[] = [
    { key: "reached", label: "My schools reached", value: v("schoolsReached"), caption: `of ${v("portfolioSchools")} in portfolio`, tone: "good" },
    { key: "ssaMissing", label: "Missing SSA", value: v("ssaMissing"), tone: v("ssaMissing") > 0 ? "alert" : "default", caption: "planning locked" },
    { key: "redFlags", label: "Red flags", value: redFlags, tone: redFlags > 0 ? "alert" : "default", caption: "SSA declines · returns · blocked" },
    { key: "visits", label: "Visits completed", value: v("visitsCompleted"), caption: ofPlanned("visitsCompleted") },
    { key: "trainings", label: "Trainings completed", value: v("trainingsCompleted"), caption: ofPlanned("trainingsCompleted") },
    { key: "partner", label: "Partner work done", value: v("partnerWorkCompleted"), caption: ofPlanned("partnerWorkCompleted")?.replace("planned", "assigned") },
    { key: "core", label: "Core schools reached", value: v("coreSchoolsReached"), caption: "4 visits + 4 trainings track" },
    target
      ? {
          key: "target", label: "Target progress", value: v("activitiesCompleted"),
          // gapToExpected = achieved − expected (negative when behind pace).
          delta: target.gapToExpected < 0
            ? { dir: "down" as const, text: `${Math.abs(target.gapToExpected)} behind pace` }
            : { dir: "up" as const, text: target.paceStatus },
          caption: `expected ${target.expectedCumulative} by now`,
        }
      : { key: "target", label: "Target progress", value: v("activitiesCompleted") },
    { key: "cost", label: "Cost of planned work", value: costLabel, unit: "UGX", caption: "in-scope activities" },
    { key: "evMissing", label: "Evidence missing", value: v("evidenceMissing"), tone: v("evidenceMissing") > 0 ? "alert" : "default" },
    { key: "sfMissing", label: "SF IDs missing", value: v("sfMissing"), tone: v("sfMissing") > 0 ? "alert" : "default", caption: "completion gate" },
    { key: "iaVerified", label: "IA verified", value: v("iaVerified"), tone: "good", caption: "evidence → SF → IA" },
  ];
  return cells.filter(Boolean) as MetricCell[];
}

// ── Compact grouped stat panel ──
function StatPanel({ title, metrics, isActive, onSelect }: { title: string; metrics: AnalyticsMetric[]; isActive: (k: string) => boolean; onSelect: (k: string) => void }) {
  if (metrics.length === 0) return null;
  return (
    <section className="card p-3">
      <h3 className="t-tiny uppercase tracking-wide muted font-bold mb-1.5">{title}</h3>
      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {metrics.map((m) => (
          <li key={m.key}>
            <button
              type="button"
              onClick={() => onSelect(m.key)}
              aria-pressed={isActive(m.key)}
              className={cn(
                "w-full flex items-center justify-between gap-2 py-1.5 px-1 -mx-1 rounded-md transition-colors text-left hover:bg-[var(--color-edify-soft)]/40",
                isActive(m.key) && "bg-[var(--color-edify-soft)]/60",
              )}
            >
              <span className="t-caption font-medium truncate">{m.label}</span>
              <span className="t-caption font-extrabold tabular shrink-0">{m.value.toLocaleString()}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Chart card wrapper ──
function ChartCard({ title, subtitle, className, children }: { title: string; subtitle?: string; className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("card p-3.5 flex flex-col", className)}>
      <div className="mb-2.5">
        <h2 className="t-body-lg font-extrabold tracking-tight leading-tight">{title}</h2>
        {subtitle && <p className="t-caption muted leading-tight">{subtitle}</p>}
      </div>
      <div className="flex-1 min-h-0">{children}</div>
    </section>
  );
}

// ── Drilldown panel ──
function DrilldownPanel({ metric, filter, onReset }: { metric: AnalyticsMetric; filter: (typeof FIELD_ANALYTICS_TILES)[number]; onReset: () => void }) {
  return (
    <section className="card p-3.5 ring-1 ring-[var(--color-edify-primary)]/15">
      <ActiveTileFilterHeader filter={filter} count={metric.records.length} onReset={onReset} />
      <p className="t-caption muted mt-1">{metric.definition}</p>
      <ul className="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-0">
        {metric.records.length === 0 && (
          <li className="py-6 text-center t-caption muted inline-flex items-center gap-2 justify-center w-full col-span-full"><Inbox size={14} /> No records behind this number for the current filters.</li>
        )}
        {metric.records.map((r) => (
          <li key={r.id} className="py-1.5 flex items-center gap-3 border-b border-[var(--color-edify-divider)]">
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", r.contributesToCount ? "bg-[var(--color-success)]" : "bg-[var(--text-muted)]")} />
            <div className="min-w-0 flex-1">
              <div className="t-caption font-semibold truncate">{r.title}</div>
              {r.subtitle && <div className="t-tiny muted truncate">{r.subtitle}</div>}
            </div>
            {!r.contributesToCount && <span className="t-tiny uppercase tracking-wide text-[var(--text-muted)] shrink-0">excluded</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Data-quality strip ──
function DataQualityStrip({ score, notes }: { score: string; notes: string[] }) {
  const tone =
    score === "Excellent" ? { fg: "var(--color-success)", bg: "var(--color-success-soft)" }
    : score === "Good" ? { fg: "var(--color-edify-primary)", bg: "var(--color-edify-soft)" }
    : score === "Needs Attention" ? { fg: "#92400e", bg: "var(--color-warn-soft)" }
    : { fg: "var(--color-danger)", bg: "var(--color-danger-soft)" };
  return (
    <div className="card px-3.5 py-2 flex items-center gap-2.5">
      <AlertTriangle size={13} style={{ color: tone.fg }} className="shrink-0" />
      <span className="t-caption font-bold uppercase tracking-wide shrink-0" style={{ color: tone.fg }}>Data quality</span>
      <span className="t-caption font-bold px-2 py-0.5 rounded-full shrink-0" style={{ backgroundColor: tone.bg, color: tone.fg }}>{score}</span>
      <span className="t-caption muted truncate">{notes.length === 0 ? "Every metric is fully sourced in this scope." : notes[0]}{notes.length > 1 ? ` · +${notes.length - 1} more` : ""}</span>
    </div>
  );
}

// ── District ranking table ──
function DistrictComparison({ rows }: { rows: AnalyticsSnapshot["districtComparison"] }) {
  if (rows.length === 0) return <ChartCard title="District comparison"><p className="t-caption muted">No districts in scope.</p></ChartCard>;
  const maxReach = Math.max(1, ...rows.map((r) => r.schoolsReached));
  return (
    <section className="card p-3.5 h-full">
      <div className="mb-2.5">
        <h2 className="t-body-lg font-extrabold tracking-tight leading-tight">District comparison</h2>
        <p className="t-caption muted leading-tight">Ranked by schools reached in the current scope.</p>
      </div>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-[var(--color-edify-divider)]">
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 pr-3">District</th>
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 px-2">Reach</th>
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 px-2 text-right">Learners</th>
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 px-2 text-right">Teachers</th>
            <th className="t-tiny uppercase tracking-wide muted font-bold py-1.5 pl-2 text-right">Avg SSA</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.district} className="border-b border-[var(--color-edify-divider)] last:border-0">
              <td className="t-caption font-semibold py-2 pr-3 whitespace-nowrap">{r.district}</td>
              <td className="py-2 px-2 w-[40%]">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-2 rounded-full bg-[var(--surface-2)] overflow-hidden">
                    <div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${(r.schoolsReached / maxReach) * 100}%` }} />
                  </div>
                  <span className="t-caption tabular font-bold w-6 text-right">{r.schoolsReached}</span>
                </div>
              </td>
              <td className="t-caption tabular py-2 px-2 text-right">{r.learnersImpacted.toLocaleString()}</td>
              <td className="t-caption tabular py-2 px-2 text-right">{r.teachersTrained}</td>
              <td className="t-caption tabular py-2 pl-2 text-right font-semibold">{r.avgSsa ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ── Filter-respecting CSV export ──
function exportSnapshotCsv(snapshot: AnalyticsSnapshot, selection: FilterSelection, generatedBy: string) {
  const esc = (v: string | number) => {
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const show = (v: string) => (v && v !== ALL_SENTINEL ? v : "All");
  const lines: string[][] = [
    ["Edify Analytics Export"],
    ["FY", snapshot.fyId, "Quarter", show(selection.quarter)],
    ["Region", show(selection.region), "District", show(selection.district)],
    ["Generated by", generatedBy, "Data quality", snapshot.dataQualityScore],
    [],
    ["Metric", "Value", "Planned", "Completed", "Verified", "Donor-ready", "Definition"],
    ...snapshot.metrics.map((m) => [
      m.label, String(m.value), String(m.breakdown.planned), String(m.breakdown.completed),
      String(m.breakdown.verified), String(m.breakdown.donorReady), m.definition,
    ]),
  ];
  const csv = lines.map((row) => row.map(esc).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `analytics-FY${snapshot.fyId}-${show(selection.district)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
