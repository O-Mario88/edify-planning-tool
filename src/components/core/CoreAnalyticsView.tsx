// Core analytics — presentational charts over the aggregated lifecycle
// (src/lib/core/core-analytics). Lightweight CSS/SVG so it renders on the
// server with no client chart runtime: lifecycle funnel, package progress,
// visits/trainings 1–4, baseline-vs-follow-up, staff-vs-partner, heatmap.

import { cn } from "@/lib/utils";
import type { CoreAnalytics } from "@/lib/core/core-analytics";

export function CoreAnalyticsView({ a }: { a: CoreAnalytics }) {
  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5">
        <Kpi label="Candidates" value={a.candidates} />
        <Kpi label="Verified" value={a.verified} />
        <Kpi label="Onboarded" value={a.onboarded} />
        <Kpi label="Active plans" value={a.activePlans} />
        <Kpi label="4+4 complete" value={a.packageComplete} />
        <Kpi label="Follow-up done" value={a.followUpDone} />
        <Kpi label="Champions" value={a.championCandidates + a.verifiedChampions} tone="text-amber-700" />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel title="Core Lifecycle Funnel">
          <Funnel stages={a.funnel} />
        </Panel>
        <Panel title="Package progress — Visits & Trainings 1–4">
          <SeqChart rows={a.sequenceProgress} plans={a.scope.plans} />
        </Panel>
        <Panel title="SSA Before / After (schools with follow-up)">
          {a.beforeAfter.length === 0 ? <Empty>No follow-up SSAs measured yet.</Empty> : <BeforeAfter rows={a.beforeAfter} />}
        </Panel>
        <Panel title="Staff vs Partner delivery (completed)">
          <Delivery staff={a.delivery.staff} partner={a.delivery.partner} />
        </Panel>
        <Panel title="Priority intervention improvement">
          {a.priorityImprovement.length === 0 ? <Empty>No measured priority changes yet.</Empty> : <PriorityBars rows={a.priorityImprovement} />}
        </Panel>
        <Panel title="Average package completion">
          <Gauge percent={a.avgPackagePercent} />
        </Panel>
      </div>

      <Panel title="Intervention heatmap (latest known SSA score per area)">
        {a.heatmap.rows.length === 0 ? <Empty>No core schools in scope.</Empty> : <Heatmap areas={a.heatmap.areas} rows={a.heatmap.rows} />}
      </Panel>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card p-3.5">
      <h2 className="text-[12px] font-extrabold tracking-tight mb-2.5">{title}</h2>
      {children}
    </section>
  );
}
function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-5 text-center text-[11.5px] muted italic">{children}</p>;
}

function Funnel({ stages }: { stages: CoreAnalytics["funnel"] }) {
  const max = Math.max(1, ...stages.map((s) => s.count));
  return (
    <div className="space-y-1.5">
      {stages.map((s) => (
        <div key={s.key} className="flex items-center gap-2">
          <div className="w-24 text-[10.5px] font-semibold muted text-right shrink-0">{s.label}</div>
          <div className="flex-1 h-5 rounded bg-[var(--color-edify-soft)]/50 overflow-hidden">
            <div className="h-full rounded bg-[var(--color-edify-primary)] flex items-center justify-end pr-1.5" style={{ width: `${Math.max(8, (s.count / max) * 100)}%` }}>
              <span className="text-[10px] font-extrabold text-white tabular">{s.count}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function SeqChart({ rows, plans }: { rows: CoreAnalytics["sequenceProgress"]; plans: number }) {
  const max = Math.max(1, plans);
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2">
          <div className="w-7 text-[11px] font-bold muted shrink-0">{r.label}</div>
          <div className="flex-1 space-y-1">
            <Bar label="Visits" value={r.visits} max={max} tone="bg-sky-500" />
            <Bar label="Trainings" value={r.trainings} max={max} tone="bg-violet-500" />
          </div>
        </div>
      ))}
    </div>
  );
}
function Bar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-14 text-[9.5px] muted shrink-0">{label}</span>
      <div className="flex-1 h-3 rounded bg-[var(--color-edify-soft)]/50 overflow-hidden">
        <div className={cn("h-full rounded", tone)} style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <span className="w-5 text-[10px] tabular font-bold text-right">{value}</span>
    </div>
  );
}

function BeforeAfter({ rows }: { rows: CoreAnalytics["beforeAfter"] }) {
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.schoolId} className="flex items-center gap-2 text-[11px]">
          <div className="w-28 truncate font-semibold">{r.schoolName}</div>
          <div className="flex-1 relative h-4">
            <div className="absolute inset-y-0 left-0 right-0 rounded bg-[var(--color-edify-soft)]/40" />
            <div className="absolute inset-y-0 rounded bg-emerald-400/70" style={{ left: `${(Math.min(r.baseline, r.followUp) / 10) * 100}%`, width: `${(Math.abs(r.followUp - r.baseline) / 10) * 100}%` }} />
          </div>
          <span className="tabular w-24 text-right">{r.baseline.toFixed(1)} → {r.followUp.toFixed(1)} <span className={r.change >= 0 ? "text-emerald-700" : "text-rose-700"}>({r.change >= 0 ? "+" : ""}{r.change})</span></span>
        </div>
      ))}
    </div>
  );
}

function PriorityBars({ rows }: { rows: CoreAnalytics["priorityImprovement"] }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.avgChange)));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.area} className="flex items-center gap-2 text-[11px]">
          <div className="w-32 truncate font-semibold">{r.area}</div>
          <div className="flex-1 h-3.5 rounded bg-[var(--color-edify-soft)]/50 overflow-hidden">
            <div className={cn("h-full rounded", r.avgChange >= 0 ? "bg-emerald-500" : "bg-rose-500")} style={{ width: `${(Math.abs(r.avgChange) / max) * 100}%` }} />
          </div>
          <span className={cn("w-10 text-right tabular font-bold", r.avgChange >= 0 ? "text-emerald-700" : "text-rose-700")}>{r.avgChange >= 0 ? "+" : ""}{r.avgChange}</span>
        </div>
      ))}
    </div>
  );
}

function Delivery({ staff, partner }: { staff: number; partner: number }) {
  const total = staff + partner;
  if (total === 0) return <Empty>No completed core activities yet.</Empty>;
  return (
    <div>
      <div className="flex h-6 rounded overflow-hidden">
        <div className="bg-[var(--color-edify-primary)] flex items-center justify-center text-[10px] font-extrabold text-white" style={{ width: `${(staff / total) * 100}%` }}>{staff > 0 && staff}</div>
        <div className="bg-amber-500 flex items-center justify-center text-[10px] font-extrabold text-white" style={{ width: `${(partner / total) * 100}%` }}>{partner > 0 && partner}</div>
      </div>
      <div className="flex justify-between text-[10.5px] muted mt-1.5">
        <span><span className="inline-block w-2 h-2 rounded-sm bg-[var(--color-edify-primary)] mr-1" />Staff {staff}</span>
        <span>Partner {partner}<span className="inline-block w-2 h-2 rounded-sm bg-amber-500 ml-1" /></span>
      </div>
    </div>
  );
}

function Gauge({ percent }: { percent: number }) {
  return (
    <div className="flex items-center gap-3">
      <div className="text-[28px] font-extrabold tabular leading-none">{percent}<span className="text-[14px] muted">%</span></div>
      <div className="flex-1 h-3 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
        <div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function heatTone(score: number | null): string {
  if (score == null) return "bg-slate-100 text-slate-400";
  if (score >= 8) return "bg-emerald-500 text-white";
  if (score >= 7) return "bg-emerald-300";
  if (score >= 5) return "bg-amber-300";
  return "bg-rose-400 text-white";
}
function Heatmap({ areas, rows }: { areas: readonly string[]; rows: CoreAnalytics["heatmap"]["rows"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="text-left font-semibold muted pr-2">School</th>
            {areas.map((a) => <th key={a} className="px-0.5 font-semibold muted align-bottom"><div className="h-16 whitespace-nowrap" style={{ writingMode: "vertical-rl" }}>{a}</div></th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.schoolId}>
              <td className="pr-2 font-semibold whitespace-nowrap">{r.schoolName}</td>
              {r.scores.map((sc, i) => (
                <td key={i} className={cn("w-7 h-7 text-center align-middle rounded tabular font-bold", heatTone(sc))}>{sc ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
