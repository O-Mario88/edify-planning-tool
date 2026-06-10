"use client";

// Recruitment Intelligence — "recruit more, or focus on current schools?"
// Advisory, role-scoped, backend-driven. Reads as a decision aid, never an
// automated action. Used on CD/RVP/IA/PL dashboards (and CCEO as advisory).

import { useEffect, useState } from "react";
import { Compass, TrendingUp, TrendingDown, CircleDot, MapPin, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeRecruitment } from "@/lib/api/surfaces";
import { LoadingState } from "@/components/ui/DataStates";

const RECO_TONE: Record<string, { bg: string; fg: string; ring: string }> = {
  "Continue Recruiting": { bg: "bg-emerald-50", fg: "text-emerald-700", ring: "border-emerald-200" },
  "Recruit More in Specific Districts": { bg: "bg-emerald-50", fg: "text-emerald-700", ring: "border-emerald-200" },
  "Recruit Carefully": { bg: "bg-amber-50", fg: "text-amber-700", ring: "border-amber-200" },
  "Stop Recruitment in Specific Districts": { bg: "bg-orange-50", fg: "text-orange-700", ring: "border-orange-200" },
  "Pause Recruitment and Support Current Schools": { bg: "bg-rose-50", fg: "text-rose-700", ring: "border-rose-200" },
};

function scoreTone(s: number): string {
  if (s >= 75) return "#10b981";
  if (s >= 55) return "#f59e0b";
  return "#ef4444";
}

export function RecruitmentIntelligenceCard({ advisory = false }: { advisory?: boolean }) {
  const [data, setData] = useState<(BeRecruitment & { live?: boolean }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [off, setOff] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/analytics/recruitment", { credentials: "include" });
        const j = await res.json();
        if (!alive) return;
        if (j.live) { setData(j); setOff(false); } else { setOff(true); }
      } catch { if (alive) setOff(true); }
      if (alive) setLoading(false);
    })();
    return () => { alive = false; };
  }, []);

  if (off) return null;
  const tone = data ? RECO_TONE[data.recommendation] ?? RECO_TONE["Recruit Carefully"] : null;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Compass size={14} /> Recruitment Intelligence{advisory ? " · advisory" : ""}
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 text-indigo-700 px-2 py-0.5 text-[10px] font-bold border border-indigo-200">
          Live · scoped · decision aid
        </span>
      </header>

      {loading || !data ? (
        <LoadingState compact />
      ) : (
        <>
          {/* Headline: score ring + recommendation */}
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <div className="grid place-items-center w-16 h-16 rounded-full border-4 shrink-0" style={{ borderColor: scoreTone(data.readinessScore) }}>
              <div className="text-[18px] font-extrabold tabular leading-none" style={{ color: scoreTone(data.readinessScore) }}>{data.readinessScore}</div>
              <div className="text-[7px] uppercase tracking-wide muted">readiness</div>
            </div>
            <div className="flex-1 min-w-[200px]">
              <div className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-[12px] font-extrabold mb-1", tone?.bg, tone?.fg, tone?.ring)}>{data.recommendation}</div>
              <p className="text-[11.5px] text-slate-600 leading-snug">{data.reason}</p>
            </div>
          </div>

          {/* Signal grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <Mini label="Current-FY SSA" value={`${data.ssaReadiness.currentSsaPct}%`} sub={`${data.ssaReadiness.missingCurrentSsa} missing`} />
            <Mini label="Schools reached" value={`${data.capacity.reachedPct}%`} sub={`${data.capacity.totalSchools} schools`} />
            <Mini label="Partner strain" value={`${data.capacity.partnerStrainPct}%`} sub={`${data.capacity.partnerEvidencePending} ev. pending`} />
            <Mini label="Impact ready" value={`${data.ssaReadiness.impactReadyPct}%`} sub={`${data.impact.schoolsImproved}↑ ${data.impact.schoolsDeclined}↓`} />
          </div>

          {/* District expand / pause (hidden in CCEO advisory mode) */}
          {!advisory && (data.suggestedRecruitDistricts.length > 0 || data.pauseDistricts.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
              <DistrictList title="Recruit more here" Icon={TrendingUp} tone="emerald" rows={data.suggestedRecruitDistricts} />
              <DistrictList title="Pause / focus here" Icon={TrendingDown} tone="rose" rows={data.pauseDistricts} />
            </div>
          )}

          <div className="rounded-md bg-slate-50 border border-slate-200 px-2.5 py-1.5 mb-2">
            <div className="text-[10px] font-bold uppercase tracking-wide muted inline-flex items-center gap-1"><CircleDot size={11} /> Next action</div>
            <p className="text-[11.5px] text-slate-700">{data.nextAction}</p>
          </div>

          <p className="text-[10px] muted inline-flex items-start gap-1"><TriangleAlert size={11} className="mt-px shrink-0 text-amber-500" /> {data.disclaimer}</p>
        </>
      )}
    </section>
  );
}

function Mini({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2">
      <div className="text-[16px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-[9.5px] muted mt-1 leading-tight">{label}<span className="block text-[9px] text-slate-400">{sub}</span></div>
    </div>
  );
}

function DistrictList({ title, Icon, tone, rows }: { title: string; Icon: typeof TrendingUp; tone: "emerald" | "rose"; rows: { district: string; ssaCompletionPct: number; score: number }[] }) {
  const toneCls = tone === "emerald" ? "text-emerald-700" : "text-rose-700";
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2">
      <div className={cn("text-[10px] font-bold uppercase tracking-wide mb-1 inline-flex items-center gap-1", toneCls)}><Icon size={11} /> {title}</div>
      {rows.length === 0 ? (
        <p className="text-[10.5px] muted">None flagged.</p>
      ) : (
        <ul className="space-y-0.5">
          {rows.slice(0, 5).map((d) => (
            <li key={d.district} className="flex items-center justify-between text-[11px]">
              <span className="inline-flex items-center gap-1 font-semibold"><MapPin size={10} className="text-slate-400" />{d.district}</span>
              <span className="muted text-[10px]">{d.ssaCompletionPct}% SSA · score {d.score}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
