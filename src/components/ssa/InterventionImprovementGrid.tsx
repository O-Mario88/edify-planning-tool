"use client";

// Intervention Improvement = previous-FY vs current-FY CHANGE per intervention,
// per group. Impact (did schools improve?), distinct from performance (current
// score). Only schools with both prev + current SSA count; the rest are flagged
// "no comparison". Backend-driven, scoped, Client+Core by default.

import { useEffect, useState, useCallback } from "react";
import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeInterventionImprovement } from "@/lib/api/surfaces";

const GROUPS = [
  { key: "district", label: "District" }, { key: "region", label: "Region" },
  { key: "cceo", label: "CCEO" }, { key: "cluster", label: "Cluster" },
];
const TYPES = [{ key: "all", label: "All" }, { key: "core", label: "Core" }, { key: "client", label: "Client" }];
const ABBR: Record<string, string> = {
  CHRIST_LIKE_BEHAVIOR: "CB", EXPOSURE_TO_WORD_OF_GOD: "WG", LEADERSHIP_BEST_PRACTICE: "LP", TEACHING_ENVIRONMENT: "TE",
  LEARNING_ENVIRONMENT: "LE", GOVERNMENT_REQUIREMENTS: "GR", FEES_BUDGET_ACCOUNTS: "FB", ENROLLMENT: "EN",
};

function changeTone(v: number | null): { bg: string; fg: string } {
  if (v == null) return { bg: "#f1f5f9", fg: "#94a3b8" };
  if (v >= 0.5) return { bg: "#10b981", fg: "#ffffff" };
  if (v > 0.05) return { bg: "#a7f3d0", fg: "#065f46" };
  if (v < -0.05) return { bg: "#fecaca", fg: "#991b1b" };
  return { bg: "#e2e8f0", fg: "#475569" };
}
const fmt = (v: number | null) => (v == null ? "—" : v > 0 ? `+${v}` : `${v}`);

export function InterventionImprovementGrid() {
  const [groupBy, setGroupBy] = useState("district");
  const [schoolType, setSchoolType] = useState("core");
  const [data, setData] = useState<(BeInterventionImprovement & { live?: boolean }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [off, setOff] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/analytics/intervention-improvement?groupBy=${groupBy}&schoolType=${schoolType}`, { credentials: "include" });
      const j = await res.json();
      if (j.live) { setData(j); setOff(false); } else { setOff(true); }
    } catch { setOff(true); }
    setLoading(false);
  }, [groupBy, schoolType]);

  useEffect(() => { void load(); }, [load]);
  if (off) return null;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><TrendingUp size={14} /> Intervention Improvement{data ? ` · FY${data.prevFy}→FY${data.currentFy}` : ""}</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped · impact</span>
      </header>

      <div className="flex items-center gap-2 mb-2.5 flex-wrap">
        <Pills options={GROUPS} value={groupBy} onChange={setGroupBy} />
        <span className="text-slate-300">·</span>
        <Pills options={TYPES} value={schoolType} onChange={setSchoolType} />
      </div>

      {loading || !data ? (
        <div className="py-8 text-center text-[12px] muted">Loading…</div>
      ) : (
        <>
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-[11px] px-1 border-separate border-spacing-x-0.5 border-spacing-y-1">
            <thead>
              <tr className="text-left muted font-bold uppercase tracking-wide">
                <th className="py-1 pr-2 text-[9.5px] sticky left-0 z-10 bg-[var(--surface-1)] w-[1%] whitespace-nowrap">{GROUPS.find((g) => g.key === groupBy)?.label}</th>
                <th className="py-1 px-1 text-[9px] text-center w-[1%] whitespace-nowrap">↑/↓</th>
                {data.interventions.map((iv) => <th key={iv.code} className="py-1 px-0.5 text-[9px] text-center min-w-[30px]" title={`${iv.label} (change)`}>{ABBR[iv.code] ?? iv.code.slice(0, 2)}</th>)}
                <th className="py-1 pl-1.5 text-[9px] w-[1%] whitespace-nowrap">Best ↑</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.groupId} className="group">
                  <td className="py-1 pr-2 font-semibold whitespace-nowrap text-[10.5px] sticky left-0 z-10 bg-[var(--surface-1)] group-hover:bg-[var(--surface-3)] w-[1%]">
                    {r.groupName}
                    {r.schoolsNoComparison > 0 && <span className="ml-1 text-[9px] text-amber-600" title="schools with no previous-FY SSA">({r.schoolsNoComparison} no comp.)</span>}
                  </td>
                  <td className="py-1 px-1 text-center text-[10px] tabular w-[1%] whitespace-nowrap">
                    <span className="text-emerald-600 font-bold">{r.schoolsImproved}</span>
                    <span className="muted">/</span>
                    <span className="text-rose-600 font-bold">{r.schoolsDeclined}</span>
                    {r.improvementRate != null && <span className="ml-1 text-[9px] muted">{r.improvementRate}%</span>}
                  </td>
                  {data.interventions.map((iv) => {
                    const cell = r.interventions.find((i) => i.code === iv.code);
                    const v = cell?.change ?? null;
                    const t = changeTone(v);
                    return <td key={iv.code} className="text-center"><span title={cell ? `${cell.prevAvg ?? "—"} → ${cell.currAvg ?? "—"}` : ""} className="inline-block w-full min-w-[30px] py-1 rounded text-[10px] font-extrabold tabular" style={{ backgroundColor: t.bg, color: t.fg }}>{fmt(v)}</span></td>;
                  })}
                  <td className="py-1 pl-1.5 text-[10px] whitespace-nowrap w-[1%]">
                    {r.bestIntervention ? <span className="text-emerald-700 font-bold">{ABBR[r.bestIntervention.code]} +{r.bestIntervention.change}</span> : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[9.5px] muted sm:hidden">Swipe sideways to see all 8 interventions →</p>
        </>
      )}
      <p className="mt-2 text-[10.5px] muted">Cells show the change from FY{data?.prevFy} → FY{data?.currentFy}. Green = improved, red = declined. Only schools with both years of SSA are compared.</p>
    </section>
  );
}

function Pills({ options, value, onChange }: { options: { key: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex items-center gap-1">
      {options.map((o) => (
        <button key={o.key} onClick={() => onChange(o.key)} className={cn("px-2 py-0.5 rounded-full text-[11px] font-bold border", value === o.key ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40")}>{o.label}</button>
      ))}
    </div>
  );
}
