"use client";

// Layer 3 — Support-to-Improvement Insight.
//
// "What support happened BEFORE SSA, and how is it associated with improvement?"
// Strictly association language — never causation. The backend already enforces
// the timing rule (only verified support dated before the current SSA counts).

import { useEffect, useState, useCallback } from "react";
import { GitCompareArrows, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeSupportCorrelation, BeStaffVsPartner } from "@/lib/api/surfaces";

const SUPPORT_FILTERS = [
  { key: "all", label: "All support" },
  { key: "visit", label: "Visits" },
  { key: "training", label: "Trainings" },
  { key: "staff", label: "Staff" },
  { key: "certified_partner", label: "Certified partner" },
  { key: "project", label: "Project" },
];

const CLASS_LABEL: Record<string, string> = { staff: "Staff-supported", certified_partner: "Certified-partner", mixed: "Mixed support" };

function changeTone(v: number | null): { bg: string; fg: string } {
  if (v == null) return { bg: "#f1f5f9", fg: "#94a3b8" };
  if (v >= 0.5) return { bg: "#10b981", fg: "#fff" };
  if (v > 0.05) return { bg: "#a7f3d0", fg: "#065f46" };
  if (v < -0.05) return { bg: "#fecaca", fg: "#991b1b" };
  return { bg: "#e2e8f0", fg: "#475569" };
}
const fmt = (v: number | null) => (v == null ? "—" : v > 0 ? `+${v}` : `${v}`);

export function SupportImprovementCard() {
  const [support, setSupport] = useState("all");
  const [corr, setCorr] = useState<BeSupportCorrelation | null>(null);
  const [svp, setSvp] = useState<BeStaffVsPartner | null>(null);
  const [loading, setLoading] = useState(true);
  const [off, setOff] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/analytics/correlation?support=${support}`, { credentials: "include" });
      const j = await res.json();
      if (j.live) { setCorr(j.correlation); setSvp(j.staffVsPartner); setOff(false); } else { setOff(true); }
    } catch { setOff(true); }
    setLoading(false);
  }, [support]);

  useEffect(() => { void load(); }, [load]);
  if (off) return null;

  const s = corr?.summary;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <GitCompareArrows size={14} /> Support → Improvement{corr ? ` · FY${corr.prevFy}→FY${corr.currentFy}` : ""}
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-violet-50 text-violet-700 px-2 py-0.5 text-[10px] font-bold border border-violet-200">
          Live · scoped · association only
        </span>
      </header>

      <div className="flex items-center gap-1 mb-3 flex-wrap">
        {SUPPORT_FILTERS.map((f) => (
          <button key={f.key} onClick={() => setSupport(f.key)} className={cn(
            "px-2 py-0.5 rounded-full text-[11px] font-bold border",
            support === f.key ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
          )}>{f.label}</button>
        ))}
      </div>

      {loading || !corr ? (
        <div className="py-8 text-center text-[12px] muted">Loading…</div>
      ) : (
        <>
          {/* Headline coefficient */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <Stat label="Schools compared" value={String(s?.schoolsWithComparison ?? 0)} />
            <Stat label="Association (r)" value={s?.correlation == null ? "—" : String(s.correlation)} hint={s?.strength} />
            <Stat label="Avg support / school" value={s?.avgSupport == null ? "—" : String(s.avgSupport)} />
            <Stat label="Avg SSA change" value={fmt(s?.avgImprovement ?? null)} />
          </div>

          <p className="text-[11px] text-slate-600 bg-slate-50 border border-slate-200 rounded px-2.5 py-1.5 mb-3 inline-flex items-start gap-1.5">
            <Info size={13} className="mt-px shrink-0 text-slate-400" /> {s?.interpretation}
          </p>

          {/* Staff vs certified-partner vs mixed */}
          {svp && (
            <div className="mb-3">
              <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1.5">Staff vs certified-partner support</div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {svp.groups.map((g) => (
                  <div key={g.supportClass} className="rounded-lg border border-[var(--color-edify-border)] p-2">
                    <div className="text-[11px] font-bold">{CLASS_LABEL[g.supportClass] ?? g.supportClass}</div>
                    <div className="text-[10px] muted mb-1">{g.schools} schools · avg {g.avgVerifiedSupport ?? 0} support</div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[18px] font-extrabold tabular" style={{ color: changeTone(g.avgOverallImprovement).fg === "#fff" ? "#10b981" : changeTone(g.avgOverallImprovement).fg }}>{fmt(g.avgOverallImprovement)}</span>
                      <span className="text-[10px] muted">avg SSA Δ · {g.schoolsImprovedPct ?? 0}% improved</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Intervention-level bins */}
          <div className="overflow-x-auto -mx-1">
            <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1.5 px-1">Avg change per intervention, by support volume before SSA</div>
            <table className="w-full text-[11px] px-1 border-separate border-spacing-x-0.5 border-spacing-y-1">
              <thead>
                <tr className="text-left muted font-bold uppercase tracking-wide text-[9px]">
                  <th className="py-1 pr-2">Intervention</th>
                  <th className="py-1 px-1 text-center">0 support</th>
                  <th className="py-1 px-1 text-center">1–2</th>
                  <th className="py-1 px-1 text-center">3+</th>
                </tr>
              </thead>
              <tbody>
                {corr.interventionBins.map((b) => (
                  <tr key={b.code}>
                    <td className="py-1 pr-2 font-semibold text-[10.5px] whitespace-nowrap">{b.label}</td>
                    {([["zero", b.zero, b.zeroN], ["low", b.low, b.lowN], ["high", b.high, b.highN]] as const).map(([k, v, n]) => {
                      const t = changeTone(v as number | null);
                      return <td key={k} className="text-center"><span className="inline-block w-full min-w-[48px] py-1 rounded text-[10px] font-extrabold tabular" style={{ backgroundColor: t.bg, color: t.fg }} title={`${n} schools`}>{fmt(v as number | null)}<span className="ml-0.5 opacity-70 font-semibold">·{n}</span></span></td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {corr.dataQuality.length > 0 && (
            <details className="mt-2.5">
              <summary className="text-[10.5px] font-semibold text-amber-700 cursor-pointer inline-flex items-center gap-1"><TriangleAlert size={12} /> Data quality ({corr.dataQuality.length})</summary>
              <ul className="mt-1 space-y-0.5 pl-4 list-disc">
                {corr.dataQuality.map((w, i) => <li key={i} className="text-[10px] muted">{w}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2">
      <div className="text-[18px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-[9.5px] muted mt-1 leading-tight">{label}{hint ? <span className="block text-[9px] text-violet-600 font-semibold">{hint}</span> : null}</div>
    </div>
  );
}
