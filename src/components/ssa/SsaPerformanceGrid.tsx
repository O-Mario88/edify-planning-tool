"use client";

// SSA Performance = the average of EACH of the 8 interventions for the selected
// group of schools (not one score). Backend-driven, scoped, drillable. Client +
// Core by default. groupBy: district | region | cceo | cluster | subCounty.

import { useEffect, useState, useCallback } from "react";
import { Grid3x3, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeSsaPerformanceGrouped, BeSsaDrilldownRow } from "@/lib/api/surfaces";

const GROUPS = [
  { key: "district", label: "District" }, { key: "region", label: "Region" },
  { key: "cceo", label: "CCEO" }, { key: "cluster", label: "Cluster" }, { key: "subCounty", label: "Sub-county" },
];
const TYPES = [{ key: "all", label: "All" }, { key: "core", label: "Core" }, { key: "client", label: "Client" }];
const ABBR: Record<string, string> = {
  CHRIST_LIKE_BEHAVIOR: "CB", EXPOSURE_TO_WORD_OF_GOD: "WG", LEADERSHIP_BEST_PRACTICE: "LP", TEACHING_ENVIRONMENT: "TE",
  LEARNING_ENVIRONMENT: "LE", GOVERNMENT_REQUIREMENTS: "GR", FEES_BUDGET_ACCOUNTS: "FB", ENROLLMENT: "EN",
};

function tone(v: number | null): { bg: string; fg: string } {
  if (v == null) return { bg: "#f1f5f9", fg: "#94a3b8" };
  if (v >= 8) return { bg: "#10b981", fg: "#ffffff" };
  if (v >= 7) return { bg: "#a7f3d0", fg: "#065f46" };
  if (v >= 5) return { bg: "#fde68a", fg: "#78350f" };
  return { bg: "#fecaca", fg: "#991b1b" };
}

export function SsaPerformanceGrid() {
  const [groupBy, setGroupBy] = useState("district");
  const [schoolType, setSchoolType] = useState("all");
  const [data, setData] = useState<(BeSsaPerformanceGrouped & { live?: boolean }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [off, setOff] = useState(false);
  const [drill, setDrill] = useState<{ name: string; rows: BeSsaDrilldownRow[]; loading: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/analytics/ssa-performance?groupBy=${groupBy}&schoolType=${schoolType}`, { credentials: "include" });
      const j = await res.json();
      if (j.live) { setData(j); setOff(false); } else { setOff(true); }
    } catch { setOff(true); }
    setLoading(false);
  }, [groupBy, schoolType]);

  useEffect(() => { void load(); }, [load]);

  // "By CCEO" is a supervisory lens — backend allows it only for PL/CD/IA.
  const allowCceo = data?.canGroupByCceo !== false;
  const availableGroups = allowCceo ? GROUPS : GROUPS.filter((g) => g.key !== "cceo");
  // If the viewer loses CCEO access (e.g. a CCEO landed on it), fall back.
  useEffect(() => {
    if (data && !allowCceo && groupBy === "cceo") setGroupBy("district");
  }, [data, allowCceo, groupBy]);

  async function openDrill(row: BeSsaGroupLike) {
    setDrill({ name: row.groupName, rows: [], loading: true });
    try {
      const res = await fetch(`/api/analytics/ssa-performance?drilldown=1&groupBy=${groupBy}&groupId=${encodeURIComponent(row.groupId)}&schoolType=${schoolType}`, { credentials: "include" });
      const j = await res.json();
      setDrill({ name: row.groupName, rows: Array.isArray(j.rows) ? j.rows : [], loading: false });
    } catch { setDrill({ name: row.groupName, rows: [], loading: false }); }
  }

  if (off) return null; // backend not enabled/reachable — page's mock layer remains

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Grid3x3 size={14} /> SSA Performance · 8 interventions</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped{data ? ` · FY${data.fy}` : ""}</span>
      </header>

      <div className="flex items-center gap-2 mb-2.5 flex-wrap">
        <Pills options={availableGroups} value={groupBy} onChange={setGroupBy} />
        <span className="text-slate-300">·</span>
        <Pills options={TYPES} value={schoolType} onChange={setSchoolType} />
      </div>

      {loading || !data ? (
        <div className="py-8 text-center text-[12px] muted">Loading…</div>
      ) : (
        <>
        <div className="overflow-x-auto -mx-1 scroll-px-2">
          <table className="w-full text-[11px] px-1 border-separate border-spacing-x-0.5 border-spacing-y-1">
            <thead>
              <tr className="text-left muted font-bold uppercase tracking-wide">
                <th className="py-1 pr-2 text-[9.5px] sticky left-0 z-10 bg-[var(--surface-1)] w-[1%] whitespace-nowrap">{GROUPS.find((g) => g.key === groupBy)?.label}</th>
                <th className="py-1 px-1 text-[9px] text-center w-[1%] whitespace-nowrap">Assd</th>
                {data.interventions.map((iv) => (
                  <th key={iv.code} className="py-1 px-0.5 text-[9px] text-center min-w-[30px]" title={iv.label}>{ABBR[iv.code] ?? iv.code.slice(0, 2)}</th>
                ))}
                <th className="py-1 px-1 text-[9px] text-center min-w-[30px]">Avg</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.groupId} className="group cursor-pointer" onClick={() => openDrill(r)}>
                  <td className="py-1 pr-2 font-semibold whitespace-nowrap text-[10.5px] sticky left-0 z-10 bg-[var(--surface-1)] group-hover:bg-[var(--surface-3)] w-[1%]">
                    <span className="inline-flex items-center gap-0.5">{r.groupName}<ChevronRight size={10} className="opacity-40" /></span>
                  </td>
                  <td className="py-1 px-1 text-center text-[10px] tabular muted w-[1%] whitespace-nowrap">{r.schoolsAssessed}/{r.schoolCount}</td>
                  {data.interventions.map((iv) => {
                    const v = r.interventions[iv.code];
                    const t = tone(v);
                    return <td key={iv.code} className="text-center"><span className="inline-block w-full min-w-[30px] py-1 rounded text-[10px] font-extrabold tabular" style={{ backgroundColor: t.bg, color: t.fg }}>{v ?? "—"}</span></td>;
                  })}
                  <td className="text-center"><span className="inline-block w-full min-w-[30px] py-1 rounded text-[10px] font-extrabold tabular ring-1 ring-black/5" style={{ backgroundColor: tone(r.overallAverage).bg, color: tone(r.overallAverage).fg }}>{r.overallAverage ?? "—"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[9.5px] muted sm:hidden">Swipe the table sideways to see all 8 interventions →</p>
        </>
      )}

      {drill && (
        <div className="mt-3 border-t border-[var(--color-edify-divider)] pt-2.5">
          <div className="flex items-center justify-between mb-1.5">
            <h3 className="text-[12px] font-extrabold">{drill.name} — {drill.loading ? "loading…" : `${drill.rows.length} school(s)`}</h3>
            <button onClick={() => setDrill(null)} className="muted hover:text-[var(--color-edify-text)]"><X size={14} /></button>
          </div>
          {!drill.loading && (
            <div className="max-h-64 overflow-y-auto rounded-lg border border-[var(--color-edify-divider)]">
              <table className="w-full text-[10.5px]">
                <thead><tr className="text-left muted uppercase text-[9px] border-b border-[var(--color-edify-divider)]"><th className="px-2 py-1">School</th><th className="px-1 py-1">Type</th><th className="px-1 py-1 text-right">Avg</th></tr></thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {drill.rows.map((s) => (
                    <tr key={s.schoolId}><td className="px-2 py-1 font-semibold">{s.name}<span className="muted font-normal"> · {s.schoolId}</span></td><td className="px-1 py-1 capitalize muted">{s.schoolType}</td><td className="px-1 py-1 text-right tabular font-bold">{s.overallAverage ?? "—"}</td></tr>
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

type BeSsaGroupLike = { groupId: string; groupName: string };

function Pills({ options, value, onChange }: { options: { key: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex items-center gap-1">
      {options.map((o) => (
        <button key={o.key} onClick={() => onChange(o.key)} className={cn("px-2 py-0.5 rounded-full text-[11px] font-bold border", value === o.key ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40")}>{o.label}</button>
      ))}
    </div>
  );
}
