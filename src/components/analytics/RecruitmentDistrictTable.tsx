"use client";

// District-level recruitment drilldown — the per-district breakdown behind the
// headline recommendation. Each row carries an expand / hold / pause signal so
// leaders can see exactly where to add schools and where to focus on current
// ones. Aggregate only — no operational school actions (spec §18).

import { useEffect, useState } from "react";
import { MapPin, TrendingUp, Minus, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeRecruitment, BeRecruitmentDistrict } from "@/lib/api/surfaces";

const SIGNAL: Record<string, { label: string; cls: string; Icon: typeof TrendingUp }> = {
  expand: { label: "Recruit more", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", Icon: TrendingUp },
  hold: { label: "Hold", cls: "bg-slate-50 text-slate-600 border-slate-200", Icon: Minus },
  pause: { label: "Pause / focus", cls: "bg-rose-50 text-rose-700 border-rose-200", Icon: TrendingDown },
};

function bar(pct: number, tone: string) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-1.5 w-14 rounded-full bg-slate-100 overflow-hidden align-middle">
        <span className="block h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, pct))}%`, backgroundColor: tone }} />
      </span>
      <span className="tabular text-[10.5px] muted">{pct}%</span>
    </span>
  );
}

export function RecruitmentDistrictTable() {
  const [districts, setDistricts] = useState<BeRecruitmentDistrict[] | null>(null);
  const [off, setOff] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<"score" | "ssa" | "schools">("score");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/analytics/recruitment", { credentials: "include" });
        const j: BeRecruitment & { live?: boolean } = await res.json();
        if (!alive) return;
        if (j.live) { setDistricts(j.districts ?? []); setOff(false); } else { setOff(true); }
      } catch { if (alive) setOff(true); }
      if (alive) setLoading(false);
    })();
    return () => { alive = false; };
  }, []);

  if (off) return null;

  const rows = [...(districts ?? [])].sort((a, b) =>
    sort === "ssa" ? a.ssaCompletionPct - b.ssaCompletionPct
      : sort === "schools" ? b.schools - a.schools
        : a.score - b.score,
  );

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <MapPin size={14} /> Recruitment readiness by district
        </h2>
        <div className="inline-flex items-center gap-1 text-[10px]">
          <span className="muted font-semibold mr-1">Sort</span>
          {([["score", "Readiness"], ["ssa", "SSA %"], ["schools", "Size"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setSort(k)} className={cn("px-1.5 py-0.5 rounded-full font-bold border", sort === k ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "muted border-[var(--color-edify-border)]")}>{label}</button>
          ))}
        </div>
      </header>

      {loading ? (
        <div className="py-8 text-center text-[12px] muted">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="py-8 text-center text-[12px] muted">No districts in scope.</div>
      ) : (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-[11px] px-1 border-separate border-spacing-y-1">
            <thead>
              <tr className="text-left muted font-bold uppercase tracking-wide text-[9.5px]">
                <th className="py-1 pr-2">District</th>
                <th className="py-1 px-2 text-center">Schools</th>
                <th className="py-1 px-2">Current SSA</th>
                <th className="py-1 px-2">Clustered</th>
                <th className="py-1 px-2">Reached</th>
                <th className="py-1 px-2 text-center">Readiness</th>
                <th className="py-1 pl-2 text-right">Signal</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const sig = SIGNAL[d.signal] ?? SIGNAL.hold;
                return (
                  <tr key={d.districtId} className="hover:bg-[var(--color-edify-soft)]/30">
                    <td className="py-1.5 pr-2 font-semibold text-[11px] whitespace-nowrap">{d.district}</td>
                    <td className="py-1.5 px-2 text-center tabular">{d.schools}</td>
                    <td className="py-1.5 px-2">{bar(d.ssaCompletionPct, d.ssaCompletionPct >= 80 ? "#10b981" : d.ssaCompletionPct >= 50 ? "#f59e0b" : "#ef4444")}</td>
                    <td className="py-1.5 px-2">{bar(d.clusteredPct, "#6366f1")}</td>
                    <td className="py-1.5 px-2">{bar(d.reachedPct, "#0ea5e9")}</td>
                    <td className="py-1.5 px-2 text-center">
                      <span className="tabular font-extrabold text-[12px]" style={{ color: d.score >= 75 ? "#10b981" : d.score >= 50 ? "#f59e0b" : "#ef4444" }}>{d.score}</span>
                    </td>
                    <td className="py-1.5 pl-2 text-right">
                      <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] font-bold", sig.cls)}>
                        <sig.Icon size={10} /> {sig.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[10.5px] muted">Readiness blends current-FY SSA, clustering, and reach. Aggregate view — open Analytics for source figures; operational school actions live with CCEO/PL/IA.</p>
    </section>
  );
}
