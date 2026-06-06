"use client";

import { useState } from "react";
import { Database, AlertTriangle, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ContributionSummary, ContributionLens, ContributionMetricKey } from "@/lib/api/surfaces";

// "My Contribution to School Improvement" — the scope-enforced contribution lens.
// CCEO sees a single own-work lens; PL gets own / team / combined tabs (the team
// layer is the supervised CCEOs). Every number is backend-computed against the
// caller's scope; drillable cards fetch the underlying records on click (scope
// re-checked server-side).

type Lenses = Partial<Record<ContributionLens, ContributionSummary>>;

const LENS_LABEL: Record<ContributionLens, string> = {
  own: "My Field Work",
  team: "My Team",
  combined: "Combined Impact",
};

type CardDef = { key: keyof ContributionSummary["metrics"]; label: string; drill?: ContributionMetricKey; tone?: "good" | "alert" };
const CARDS: CardDef[] = [
  { key: "schoolsReached", label: "Schools Reached", drill: "schoolsReached" },
  { key: "coreSchoolsSupported", label: "Core Schools Supported" },
  { key: "learnersImpacted", label: "Learners Impacted", drill: "learnersImpacted" },
  { key: "teachersTrained", label: "Teachers Trained", drill: "teachersTrained" },
  { key: "schoolLeadersTrained", label: "School Leaders Trained", drill: "schoolLeadersTrained" },
  { key: "districtsCovered", label: "Districts Covered", drill: "districtsCovered" },
  { key: "clustersCovered", label: "Clusters Covered" },
  { key: "visitsCompleted", label: "Visits Completed" },
  { key: "trainingsCompleted", label: "Trainings Completed" },
  { key: "ssaCompleted", label: "SSA Completed" },
  { key: "schoolsImproved", label: "Schools Improved", drill: "ssaImprovement", tone: "good" },
  { key: "partnerActivities", label: "Partner Activities Managed" },
  { key: "iaVerifiedActivities", label: "IA-Verified Activities", tone: "good" },
  { key: "evidencePending", label: "Evidence Pending", tone: "alert" },
];

export function MyContribution({ title, fy, lenses }: { title: string; fy: string; lenses: Lenses }) {
  const available = (Object.keys(lenses) as ContributionLens[]).filter((k) => lenses[k]);
  const [active, setActive] = useState<ContributionLens>(available[0] ?? "own");
  const [drill, setDrill] = useState<{ metric: ContributionMetricKey; label: string; rows: Record<string, unknown>[]; loading: boolean } | null>(null);

  const summary = lenses[active];
  if (!summary) return null;
  const m = summary.metrics;

  async function openDrill(metric: ContributionMetricKey, label: string) {
    setDrill({ metric, label, rows: [], loading: true });
    try {
      const res = await fetch(`/api/analytics/contribution-drilldown?metric=${metric}&lens=${active}&fy=${fy}`, { credentials: "include" });
      const data = await res.json();
      setDrill({ metric, label, rows: Array.isArray(data.rows) ? data.rows : [], loading: false });
    } catch {
      setDrill({ metric, label, rows: [], loading: false });
    }
  }

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-3.5 pt-3 pb-2.5 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-extrabold tracking-tight">{title}</h2>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">
            <Database size={10} /> Live · scoped · FY{fy}
          </span>
        </div>
        <span className="text-[11px] muted font-semibold">{summary.schoolsInScope} schools in your scope</span>
      </header>

      {/* PL lens tabs (own / team / combined). CCEO has only own. */}
      {available.length > 1 && (
        <div className="flex items-center gap-1 px-3.5 pt-2.5">
          {available.map((k) => (
            <button
              key={k}
              onClick={() => { setActive(k); setDrill(null); }}
              className={cn(
                "px-2.5 py-1 rounded-full text-[11px] font-bold border transition-colors",
                active === k ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {LENS_LABEL[k]}
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-7 border-t border-l border-[var(--color-edify-divider)] mt-2.5">
        {CARDS.map((c) => {
          const value = m[c.key] as number;
          const drillable = !!c.drill && !summary.summaryOnly;
          return (
            <button
              key={c.key as string}
              disabled={!drillable}
              onClick={() => c.drill && openDrill(c.drill, c.label)}
              className={cn(
                "text-left px-3 py-2.5 border-r border-b border-[var(--color-edify-divider)]",
                drillable ? "hover:bg-[var(--color-edify-soft)]/40 cursor-pointer" : "cursor-default",
              )}
            >
              <div className="flex items-center gap-1 text-[10px] muted font-bold uppercase tracking-wide leading-tight">
                <span className="truncate">{c.label}</span>
                {drillable && <ChevronRight size={10} className="shrink-0 opacity-50" />}
              </div>
              <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", c.tone === "good" ? "text-emerald-600" : c.tone === "alert" && value > 0 ? "text-rose-600" : "text-[var(--text-primary)]")}>
                {value.toLocaleString()}
              </div>
            </button>
          );
        })}
      </div>

      {/* Best/worst intervention strip. */}
      {(m.bestIntervention || m.worstIntervention) && (
        <div className="px-3.5 py-2 flex items-center gap-4 text-[11px] border-b border-[var(--color-edify-divider)]">
          {m.bestIntervention && <span className="muted">Best improving: <b className="text-emerald-700">{labelize(m.bestIntervention)}</b></span>}
          {m.worstIntervention && <span className="muted">Needs attention: <b className="text-rose-700">{labelize(m.worstIntervention)}</b></span>}
        </div>
      )}

      {/* Data-quality warnings — surfaced, never hidden. */}
      {summary.dataQuality.length > 0 && (
        <div className="px-3.5 py-2 space-y-1">
          {summary.dataQuality.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5 text-[11px] text-amber-700">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" /> <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Drilldown panel — the exact records counted, scope-checked server-side. */}
      {drill && (
        <div className="px-3.5 py-2.5 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20">
          <div className="flex items-center justify-between mb-1.5">
            <h3 className="text-[12px] font-extrabold">{drill.label} — {drill.loading ? "loading…" : `${drill.rows.length} record(s)`}</h3>
            <button onClick={() => setDrill(null)} className="muted hover:text-[var(--color-edify-text)]"><X size={14} /></button>
          </div>
          {!drill.loading && drill.rows.length === 0 && <p className="text-[11px] muted italic py-2">No records in your scope.</p>}
          {!drill.loading && drill.rows.length > 0 && (
            <div className="max-h-56 overflow-y-auto rounded-lg border border-[var(--color-edify-divider)] bg-[var(--color-edify-bg)]">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left muted uppercase text-[9.5px] tracking-wide border-b border-[var(--color-edify-divider)]">
                    {Object.keys(drill.rows[0]).map((k) => <th key={k} className="px-2 py-1.5 font-bold">{k}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {drill.rows.map((r, i) => (
                    <tr key={i}>
                      {Object.values(r).map((v, j) => <td key={j} className="px-2 py-1.5 tabular">{String(v ?? "—")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function labelize(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
